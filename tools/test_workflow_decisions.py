"""Tests for tools/workflow_decisions.py: templates, the owner-file checks, the context sheet, the
freeze and check-frozen.

Everything runs on a synthetic world: a temporary MLView root with a two-task manifest, synthetic
candidate ledgers and a temporary Git corpus with pinned commits. Every decision in these tests is
synthetic (reviewer "Test Reviewer (synthetic)"); no decision for a real task is written anywhere.
The real candidate ledgers and native review ledgers are only read, to pin the exact messages of
the Campaign 2 specification. These are local tooling checks, not semantic accuracy, human review
or live-host validation.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))
import eval_records as er  # noqa: E402
import fetch_workflow_repos  # noqa: E402
import workflow_decisions as wd  # noqa: E402

REVIEWER = "Test Reviewer (synthetic)"
SECOND = "Second Test Reviewer (synthetic)"
DATE = "2026-01-02"
FROZEN_AT = "2026-01-03T10:00:00Z"
EM = "—"
HAS_GIT = shutil.which("git") is not None
pytestmark = pytest.mark.skipif(not HAS_GIT, reason="git is not installed")


def real_corpus() -> Path | None:
    return wd.default_corpus(ROOT)


needs_corpus = pytest.mark.skipif(real_corpus() is None, reason="corpus absent: set MLVIEW_PUBLIC_CORPUS_DIR or run "
                                                                 "python tools/fetch_workflow_repos.py")


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tools' own Git reads never see the developer's Git configuration (DISTCI4-2); a test that
    needs a configuration sets GIT_CONFIG_GLOBAL itself."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


# --------------------------------------------------------------------------------------------
# The synthetic world


def git_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_AUTHOR_NAME": "Synthetic Test", "GIT_AUTHOR_EMAIL": "synthetic@example.invalid",
                "GIT_COMMITTER_NAME": "Synthetic Test", "GIT_COMMITTER_EMAIL": "synthetic@example.invalid",
                "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"})
    return env


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, env=git_env(),
                          check=True).stdout.decode("utf-8")


def make_repo(path: Path, files: dict[str, bytes]) -> str:
    path.mkdir(parents=True)
    git(path, "init", "--quiet")
    for rel, data in files.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_bytes(data)
    git(path, "add", "-A")
    git(path, "commit", "--quiet", "-m", "synthetic")
    return git(path, "rev-parse", "HEAD").strip()


def numbered(prefix: str, count: int) -> bytes:
    return "".join(f"{prefix}_{n} = {n}\n" for n in range(1, count + 1)).encode("utf-8")


NOTEBOOK = {"cells": [{"cell_type": "markdown", "metadata": {}, "source": ["# Synthetic notebook\n"]},
                      {"cell_type": "code", "metadata": {}, "source": ["x = 1\n", "y = x + 1\n", "print(y)"]},
                      {"cell_type": "code", "metadata": {}, "source": "z = 3\n"}],
            "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
DEMO_FILES = {"train.py": numbered("value", 60), "lib/model.py": numbered("width", 30),
              "configs/a.py": numbered("option", 5), "configs/other.py": numbered("other", 3),
              "README.md": b"Synthetic README\n"}
BOOK_FILES = {"book.ipynb": json.dumps(NOTEBOOK, indent=1).encode("utf-8"), "helper.py": numbered("helper", 4)}
TARGETS = {"structurallyValid": 1.0, "exactAnchors": 1.0, "supportedClaimPrecision": 0.95,
           "essentialFactRecall": 0.85, "knownUnresolvedQualified": 1.0, "highSeverityFalseAccusations": 0}


def quote(files: dict[str, bytes], rel: str, line: int, end: int, cell: int | None = None) -> str:
    return er.excerpt(er.source_lines(files[rel], cell), line, end)


def anchor(ident: str, files: dict[str, bytes], rel: str, line: int, end: int, cell: int | None = None) -> dict:
    value = {"id": ident, "file": rel, "line": line, "endLine": end, "quote": quote(files, rel, line, end, cell)}
    if cell is not None:
        value["cell"] = cell
    return value


def write_json(path: Path, value: object, canonical: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2) + "\n" if canonical else json.dumps(value)
    path.write_bytes(text.encode("utf-8"))


def make_world(tmp_path: Path, *, placeholder: bool = False, uncovered_anchor: bool = False,
               prompt: str = "Explain the synthetic training loop and its defaults.") -> wd.World:
    corpus = tmp_path / "corpus"
    demo_sha = make_repo(corpus / "demo", DEMO_FILES)
    book_sha = make_repo(corpus / "book", BOOK_FILES)
    root = tmp_path / "mlview"
    tasks = {"version": 1, "hosts": ["codex", "copilot"], "repetitions": 3, "pilotTargets": dict(TARGETS), "tasks": [
        {"id": "dev-demo", "split": "development", "title": "Synthetic development task", "repository": "MLView",
         "entrypoints": ["samples/synthetic.py"], "prompt": "Synthetic development prompt.",
         "referenceStatus": "needs-human-review"},
        {"id": "pilot-demo", "split": "heldout", "title": "demo", "repository": "demo",
         "url": "https://example.invalid/demo", "commit": demo_sha, "entrypoints": ["train.py"], "prompt": prompt,
         "referenceStatus": "needs-human-review"},
        {"id": "pilot-book", "split": "heldout", "title": "book", "repository": "book",
         "url": "https://example.invalid/book", "commit": book_sha, "entrypoints": ["book.ipynb"],
         "prompt": "Explain the synthetic notebook in source order.", "referenceStatus": "needs-human-review"}]}
    write_json(root / "evals/workflow/tasks.json", tasks)
    write_json(root / "evals/workflow/repositories.json", {"repos": [
        {"name": "demo", "url": "https://example.invalid/demo", "sha": demo_sha, "license": "synthetic",
         "redistribute": False, "sparse": ["lib", "/train.py", "/configs/a.py", "/README.md"]},
        {"name": "book", "url": "https://example.invalid/book", "sha": book_sha, "license": "synthetic",
         "redistribute": False, "sparse": []}]})
    second_anchor = (anchor("demo-a02", DEMO_FILES, "configs/other.py", 1, 1) if uncovered_anchor
                     else anchor("demo-a02", DEMO_FILES, "lib/model.py", 3, 3))
    demo = {"taskId": "pilot-demo", "repositoryCommit": demo_sha, "status": "draft-needs-human-review",
            "review": {"reviewer": None, "decision": "pending"},
            "scenario": {"description": "Inspect train.py with its synthetic defaults and no overrides.",
                         "entrypoints": ["train.py"], "arguments": []},
            "facts": [
                {"id": "demo-f01", "claim": "The synthetic loop accumulates forty micro-steps before each update.",
                 "basis": "observed", "essential": True, "anchors": [anchor("demo-a01", DEMO_FILES, "train.py", 10, 11)],
                 "review": "pending"},
                {"id": "demo-f02", "claim": "The synthetic model width comes from lib/model.py constants.",
                 "basis": "observed", "essential": False, "anchors": [second_anchor], "review": "pending"},
                {"id": "demo-f03", "claim": "Synthetic evaluation probably reuses the training batch size.",
                 "basis": "inferred", "essential": True,
                 "anchors": [anchor("demo-a03", DEMO_FILES, "train.py", 20, 22),
                             anchor("demo-a04", DEMO_FILES, "configs/a.py", 2, 2)], "review": "pending"}],
            "unknowns": ["The synthetic dataset contents are not established by the source files.",
                         "Runtime hardware for the synthetic run is unknown."],
            "nonDefects": ["Dividing the synthetic loss by the step count is intentional scaling."]}
    book = {"taskId": "pilot-book", "repositoryCommit": book_sha, "status": "draft-needs-human-review",
            "review": {"reviewer": None, "decision": "pending"},
            "scenario": {"description": "Read the synthetic notebook in source order.", "entrypoints": ["book.ipynb"],
                         "arguments": ["--workdir=<reviewer-selected-directory>"] if placeholder
                         else ["source-order-only"]},
            "facts": [{"id": "book-f01", "claim": "The synthetic notebook computes y from x in its first code cell.",
                       "basis": "observed", "essential": True,
                       "anchors": [anchor("book-a01", BOOK_FILES, "book.ipynb", 1, 2, cell=1)], "review": "pending"}],
            "unknowns": ["Stored outputs of the synthetic notebook do not prove execution order."],
            "nonDefects": []}
    write_json(root / "evals/workflow/reference-candidates/pilot-demo.json", demo)
    write_json(root / "evals/workflow/reference-candidates/pilot-book.json", book)
    return wd.World(root, corpus)


def run(world: wd.World, *argv: str, corpus: object = wd._DEFAULT) -> tuple[int, str]:
    buffer = io.StringIO()
    code = wd.main(list(argv), root=world.root, corpus=world.corpus if corpus is wd._DEFAULT else corpus, out=buffer)
    return code, buffer.getvalue()


def in_section(text: str, heading: str, old: str, new: list[str]) -> str:
    lines = text.split("\n")
    start = lines.index(f"## {heading}")
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            break
        if lines[index] == old:
            lines[index:index + 1] = new
            return "\n".join(lines)
    raise AssertionError(f"{old!r} not found in ## {heading}")


def decide(text: str, heading: str, decision: str, *extra: str, runs: str | None = None) -> str:
    text = in_section(text, heading, "Decision: pending", [f"Decision: {decision}", *extra])
    if runs is not None:
        text = in_section(text, heading, "Runs must state:", [f"Runs must state: {runs}"])
    return text


def fill_header(text: str, reviewer: str = REVIEWER, date: str = DATE) -> str:
    return text.replace("\nReviewer:\n", f"\nReviewer: {reviewer}\n", 1).replace("\nDate:\n", f"\nDate: {date}\n", 1)


def complete(text: str) -> str:
    assert "\nReview: pending\n" in text
    return text.replace("\nReview: pending\n", "\nReview: complete\n")


def accept_all(world: wd.World, task_id: str, *, runs: str = "no", second: bool = False) -> str:
    text = fill_header(wd.task_template(world, task_id, second=second), SECOND if second else REVIEWER)
    ledger = world.ledger(task_id)[0]
    text = decide(text, "Scenario", "accept")
    for fact in ledger["facts"]:
        text = decide(text, f"Fact {fact['id']}", "accept")
    for ident in wd.unknown_ids(task_id, ledger):
        text = decide(text, f"Unknown {ident}", "accept", runs=runs)
    for ident in wd.nondefect_ids(task_id, ledger):
        text = decide(text, f"Non-defect {ident}", "accept")
    return text


def insert_before(text: str, marker: str, lines: list[str]) -> str:
    assert marker in text
    return text.replace(marker, "\n".join(lines) + "\n" + marker, 1)


def write(world: wd.World, name: str, text: str) -> Path:
    path = world.root / wd.DECISIONS_REL / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def fill_policy(world: wd.World, *, sessions: str = "0", adjudication: str = "not-required", **replace: str) -> str:
    text = fill_header(wd.policy_template(world))
    values = {"Model:": "Model: synthetic-model (synthetic)", "Reasoning:": "Reasoning: default (synthetic)",
              "Invocation:": "Invocation: skill picker (synthetic)",
              "Helper Python:": "Helper Python: python3 resolves to a Python 3.12 virtual environment (synthetic)",
              "Active minutes:": "Active minutes: 20", "Repair rounds:": "Repair rounds: 2",
              "Infrastructure retries:": "Infrastructure retries: 0", "Qualified claims:": "Qualified claims: not-supported",
              "Per-host targets:": "Per-host targets: no", "Baseline sessions:": f"Baseline sessions: {sessions}",
              "Development adjudication before Stage 1:": f"Development adjudication before Stage 1: {adjudication}",
              "Publication:": "Publication: counts, statuses and hashes only (synthetic)",
              "Decision: pending": "Decision: accept"}
    values.update(replace)
    lines = [values.get(line, line) for line in text.split("\n")]
    return complete("\n".join(lines))


def complete_world(world: wd.World, **policy: str) -> None:
    write(world, "pilot-demo.md", complete(accept_all(world, "pilot-demo")))
    write(world, "pilot-book.md", complete(accept_all(world, "pilot-book", runs="yes")))
    write(world, "run-policy.md", fill_policy(world, **policy))


@pytest.fixture
def verified(monkeypatch):
    """Stand in for fetch_workflow_repos.verify_repo (stream D) with an accepting verifier."""
    calls: list[str] = []

    def verify(repo: dict, corpus_root: Path) -> dict:
        calls.append(repo["name"])
        return {"name": repo["name"], "ok": True}

    monkeypatch.setattr(fetch_workflow_repos, "verify_repo", verify, raising=False)
    monkeypatch.setitem(sys.modules, "fetch_workflow_repos", fetch_workflow_repos)
    return calls


def problems_of(world: wd.World, text: str, task: str = "pilot-demo") -> list[str]:
    result = wd.check_reference(world, text.encode("utf-8"), f"{task}.md")
    return [f"{p.level:<5} {p.section}: {p.message}" for p in result.report.ordered()]


# --------------------------------------------------------------------------------------------
# Templates


def field_values(text: str, name: str) -> list[tuple[str, str]]:
    record, problems = er.parse_record(text.encode("utf-8"), name)
    assert problems == [] and record is not None
    return [(f.key, f.value) for section in [record.header, *record.sections] for f in section.lines]


def test_templates_hold_only_pending_values(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    texts = {"task": wd.task_template(world, "pilot-demo"), "notebook": wd.task_template(world, "pilot-book"),
             "second": wd.task_template(world, "pilot-demo", second=True), "policy": wd.policy_template(world)}
    for name, text in texts.items():
        for key, value in field_values(text, name):
            if key == "Candidate":
                assert re.fullmatch(r"pilot-(demo|book)\.json [0-9a-f]{64}", value)
            else:
                assert value in ("", "pending"), (name, key, value)
        assert "\nReviewer:\n" in text and "\nDate:\n" in text and "\nTranscribed by:\n" in text
        assert not wd.MACHINE_PATH_RE.search(text)
    assert "## Disagreements" in texts["task"] and "## Disagreements" not in texts["second"]
    assert texts["second"].startswith("# Second review: pilot-demo\n")
    assert "> Anchors" not in texts["notebook"] and "book.ipynb#cell1:1-2" in texts["notebook"]
    assert "Candidate: pilot-demo.json " + er.sha256_bytes(
        (world.root / "evals/workflow/reference-candidates/pilot-demo.json").read_bytes()) in texts["task"]
    assert "> Baseline sessions: 4 (one no-skill session per task and host" in texts["policy"]
    assert "## Host codex" in texts["policy"] and "## Host copilot" in texts["policy"]


def test_real_adjudication_template_holds_only_pending_verdicts() -> None:
    text = wd.adjudication_template(wd.World(ROOT, None))
    values = field_values(text, "development-adjudication.md")
    ledgers = [value for key, value in values if key.casefold() == "ledger"]
    assert len(ledgers) == 13 and all(re.fullmatch(r"native-reviews/[a-z-]+(/[a-z-]+\.json|\.json) [0-9a-f]{64}", v)
                                      for v in ledgers)
    verdicts = [(key, value) for key, value in values if key.casefold() != "ledger"]
    assert len(verdicts) == 3 + 108 + 72 + 3 + 1  # header, claims, usability, baselines, Review
    assert {value for _key, value in verdicts} == {"", "pending"}


def test_template_command_is_exclusive_and_show_prints(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    path = world.root / wd.DECISIONS_REL / "pilot-demo.md"
    code, out = run(world, "template", "pilot-demo")
    assert code == 0 and "created evals/workflow/decisions/pilot-demo.md" in out
    assert path.read_text(encoding="utf-8") == wd.task_template(world, "pilot-demo")
    path.write_text(path.read_text(encoding="utf-8") + "\n> an owner note\n", encoding="utf-8")
    edited = path.read_bytes()
    code, out = run(world, "template", "pilot-demo")
    assert code == 1 and "already exists; templates are created exclusively and never overwritten" in out
    assert path.read_bytes() == edited
    code, out = run(world, "template", "--show", "pilot-demo")
    assert code == 0 and out == wd.task_template(world, "pilot-demo")
    code, out = run(world, "template", "pilot-demo", "--second")
    assert code == 0 and (world.root / wd.DECISIONS_REL / "pilot-demo.second.md").read_text(encoding="utf-8") == \
        wd.task_template(world, "pilot-demo", second=True)
    code, out = run(world, "template", "pilot-demo", "--second")
    assert code == 1
    code, out = run(world, "template", "run-policy", "--show")
    assert code == 0 and out == wd.policy_template(world)
    assert run(world, "template", "pilot-nothing")[0] == 2
    assert run(world, "template", "run-policy", "--second")[0] == 2
    assert run(world, "template")[0] == 2


def test_init_all_refuses_existing_files_and_writes_nothing(tmp_path: Path) -> None:
    world = wd.World(ROOT, None, decisions_dir=tmp_path / "decisions")
    args = wd.build_parser().parse_args(["template", "--init-all"])
    out = io.StringIO()
    assert wd.command_template(world, args, out) == 0
    names = sorted(path.name for path in (tmp_path / "decisions").iterdir())
    assert names == sorted([f"{task['id']}.md" for task in world.heldout]
                           + ["run-policy.md", "development-adjudication.md", "README.md"])
    before = {path.name: path.read_bytes() for path in (tmp_path / "decisions").iterdir()}
    (tmp_path / "decisions" / "run-policy.md").unlink()
    out = io.StringIO()
    assert wd.command_template(world, args, out) == 1
    assert "refusing" in out.getvalue()
    assert not (tmp_path / "decisions" / "run-policy.md").exists()
    assert {p.name: p.read_bytes() for p in (tmp_path / "decisions").iterdir()} == \
        {k: v for k, v in before.items() if k != "run-policy.md"}


# --------------------------------------------------------------------------------------------
# Checking reference decisions


def test_pristine_file_lists_every_item_as_to_do(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    write(world, "pilot-demo.md", wd.task_template(world, "pilot-demo"))
    code, out = run(world, "check", "pilot-demo")
    lines = out.splitlines()
    assert code == 0
    assert lines[0] == ("evals/workflow/decisions/pilot-demo.md:10: TODO  header: Reviewer is empty. Write the name of "
                        "the person who checked the source.")
    assert lines[1] == "evals/workflow/decisions/pilot-demo.md:11: TODO  header: Date is empty. Write the review date as YYYY-MM-DD."
    assert sum(" TODO " in line for line in lines) == 2 + 1 + 3 + 2 + 1 + 1
    assert lines[-2:] == ["pilot-demo: 0 error(s), 10 to do; in progress.",
                          "  facts decided: 0 accept, 0 qualify, 0 reject; essential so far (0): -"]
    code, out = run(world, "check", "pilot-demo", corpus=None)
    assert code == 0 and out.splitlines()[-1] == "  anchors not checked: corpus absent (freeze requires it)"


def test_complete_file_is_ready_to_freeze(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    text = in_section(accept_all(world, "pilot-demo"), "Unknown demo-u01", "Runs must state: no",
                      ["Runs must state: yes"])
    write(world, "pilot-demo.md", complete(text))
    code, out = run(world, "check", "pilot-demo")
    assert code == 0
    assert out.splitlines() == [
        "pilot-demo: 0 error(s), 0 to do; ready to freeze.",
        "  facts: 3 accept, 0 qualify, 0 reject; added 0; essential (2): demo-f01 demo-f03",
        "  unknowns: 2 kept (runs must state: demo-u01); non-defects: 1 kept; defects: 0",
        f"  anchors checked against demo@{world.manifest['tasks'][1]['commit'][:12]} ({world.corpus / 'demo'})"]
    code, out = run(world, "check", "pilot-demo", corpus=None)
    assert code == 0 and out.splitlines()[-1] == "  anchors not checked: corpus absent (freeze requires it)"


RULES = [
    # (heading, decision lines, expected "LEVEL section: message" fragment)
    ("Fact demo-f01", ["Decision: accept", "Wording: My words."],
     'ERROR Fact demo-f01: Wording is used only with "Decision: qualify". Change the decision or delete the line.'),
    ("Fact demo-f01", ["Decision: qualify", "Reason: why"],
     'ERROR Fact demo-f01: Decision is qualify but there is no "Wording:" line. Add "Wording: <your corrected claim>".'),
    ("Fact demo-f01", ["Decision: qualify", "Wording: Better words."],
     'ERROR Fact demo-f01: Decision is qualify but "Reason:" is missing. Say what the proposed claim got wrong.'),
    ("Fact demo-f01", ["Decision: reject"],
     'ERROR Fact demo-f01: Decision is reject but "Reason:" is missing. Say why the claim is wrong or not needed.'),
    ("Fact demo-f01", ["Decision: reject", "Basis: inferred", "Reason: why"],
     "ERROR Fact demo-f01: a rejected fact takes no Basis; delete the line or change the decision."),
    ("Fact demo-f01", ["Decision: reject", "Anchors: train.py:1", "Reason: why"],
     "ERROR Fact demo-f01: a rejected fact takes no Anchors; delete the line or change the decision."),
    ("Fact demo-f01", ["Decision: reject", "Essential: no", "Reason: why"],
     "ERROR Fact demo-f01: a rejected fact cannot be essential; delete the Essential line or change the decision."),
    ("Fact demo-f01", ["Decision: accept", "Basis: seen"],
     'ERROR Fact demo-f01: "Basis: seen" must be observed, inferred or unresolved.'),
    ("Fact demo-f01", ["Decision: accept", "Essential: maybe"], 'ERROR Fact demo-f01: "Essential: maybe" must be yes or no.'),
    ("Fact demo-f01", ["Decision: accept", "Basis: inferred"],
     'ERROR Fact demo-f01: Basis differs from the proposal; add "Reason:" saying why.'),
    ("Fact demo-f01", ["Decision: accept", "Anchors: train.py:10-12"],
     'ERROR Fact demo-f01: Anchors differ from the proposal; add "Reason:" saying why.'),
    ("Fact demo-f01", ["Decision: accept", "Basis: inferred", "Essential: no", "Anchors: train.py:10-12"],
     'ERROR Fact demo-f01: Basis, Essential and Anchors differ from the proposal; add "Reason:" saying why.'),
    ("Fact demo-f01", ["Decision: accept", "Anchors: train.py", "Reason: why"],
     'ERROR Fact demo-f01: "train.py" is not an anchor. Write path:LINE or path:LINE-END; notebooks '
     'path#cellN:LINE-END; separate several with ";".'),
    ("Fact demo-f01", ["Decision: accept", "Anchors: train.py:10-99", "Reason: why"],
     "ERROR Fact demo-f01: train.py has 60 lines; line 99 is out of range."),
    ("Fact demo-f01", ["Decision: accept", "Anchors: missing.py:1", "Reason: why"],
     "ERROR Fact demo-f01: missing.py is not in the pinned demo tree at "),
    ("Fact demo-f01", ["Decision: accept", "Anchors: configs/other.py:1", "Reason: why"],
     "ERROR Fact demo-f01: configs/other.py is not fetched by repositories.json (demo sparse list); ask the maintainer "
     "to add it before freezing."),
    ("Fact demo-f01", ["Decision: accept", "Anchors: train.py:10-11; train.py:10-11", "Reason: why"],
     'ERROR Fact demo-f01: "train.py:10-11" is listed twice.'),
    ("Fact demo-f01", ["Decision: accept", "Anchors: none", "Reason: why"],
     "ERROR Fact demo-f01: a fact needs at least one anchor unless Basis is unresolved."),
    ("Fact demo-f01", ["Decision: aprove"],
     'ERROR Fact demo-f01: "Decision: aprove" is not a decision. Write one of: accept, qualify, reject.'),
    ("Scenario", ["Decision: accept", "Description: Something else."],
     'ERROR Scenario: Description is used only with "Decision: replace".'),
    ("Scenario", ["Decision: replace", "Description: Synthetic.", "Entrypoints: train.py", "Arguments: none"],
     'ERROR Scenario: Decision is replace but "Reason:" is missing or empty.'),
    ("Scenario", ["Decision: replace", "Description: Synthetic.", "Entrypoints: train.py; configs/other.py",
                  "Arguments: configs/a.py", "Reason: why"],
     "ERROR Scenario: configs/other.py is not fetched by repositories.json (demo sparse list); ask the maintainer to "
     "add it before freezing."),
    ("Scenario", ["Decision: replace", "Description: Synthetic.", "Entrypoints: train.py; missing.py",
                  "Arguments: none", "Reason: why"],
     "ERROR Scenario: missing.py is not in the pinned demo tree at "),
    ("Scenario", ["Decision: replace", "Description: Synthetic.", "Entrypoints: train.py",
                  "Arguments: --config=configs/a.py", "Reason: why"],
     "ERROR Scenario: argument configs/a.py is a file in the pinned tree; list it under Entrypoints too."),
    ("Scenario", ["Decision: replace", "Description: Read /Users/someone/train.py.", "Entrypoints: train.py",
                  "Arguments: none", "Reason: why"],
     "ERROR Scenario: Description contains an absolute machine path (/Users/); use paths relative to the repository."),
    ("Scenario", ["Decision: replace", "Description: Synthetic.", "Entrypoints: none", "Arguments: none", "Reason: why"],
     'ERROR Scenario: Entrypoints needs at least one path ("none" is only for Arguments).'),
    ("Scenario", ["Decision: maybe"], 'ERROR Scenario: "Decision: maybe" is not a decision. Write one of: accept, replace.'),
    ("Unknown demo-u01", ["Decision: accept"],
     'TODO  Unknown demo-u01: "Runs must state:" must be yes (every run must state this uncertainty) or no.'),
    ("Unknown demo-u01", ["Decision: reject", "Reason: why"],
     'ERROR Unknown demo-u01: a rejected unknown takes no "Runs must state"; delete the value.'),
    ("Unknown demo-u01", ["Decision: qualify", "Reason: why"],
     'ERROR Unknown demo-u01: Decision is qualify but there is no "Wording:" line. Add "Wording: <your corrected text>".'),
    ("Unknown demo-u01", ["Decision: reject"],
     'ERROR Unknown demo-u01: Decision is reject but "Reason:" is missing. Say why this is not a real uncertainty or not needed.'),
    ("Non-defect demo-n01", ["Decision: reject"],
     'ERROR Non-defect demo-n01: Decision is reject but "Reason:" is missing. Say why this is not intended behaviour or '
     "not needed."),
    ("Non-defect demo-n01", ["Decision: qualify", "Wording: Better."],
     'ERROR Non-defect demo-n01: Decision is qualify but "Reason:" is missing. Say what the proposed text got wrong.'),
    ("Non-defect demo-n01", ["Decision: accept", "Wording: Better."],
     'ERROR Non-defect demo-n01: Wording is used only with "Decision: qualify". Change the decision or delete the line.'),
]


@pytest.mark.parametrize("heading, lines, expected", RULES)
def test_recording_rules(shared_world, heading: str, lines: list[str], expected: str) -> None:
    text = in_section(accept_all(shared_world, "pilot-demo"), heading, "Decision: accept", lines)
    if heading.startswith("Unknown") and lines == ["Decision: accept"]:
        text = in_section(text, heading, "Runs must state: no", ["Runs must state:"])
    found = problems_of(shared_world, text)
    assert any(line.startswith(expected) for line in found), found


@pytest.fixture(scope="module")
def shared_world(tmp_path_factory) -> wd.World:
    return make_world(tmp_path_factory.mktemp("shared"))


def test_notebook_anchor_rules(shared_world: wd.World) -> None:
    text = accept_all(shared_world, "pilot-book")
    base = in_section(text, "Fact book-f01", "Decision: accept", ["Decision: accept", "Anchors: {}", "Reason: why"])
    cases = {"book.ipynb#cell9:1": "ERROR Fact book-f01: book.ipynb has no cell9.",
             "book.ipynb#cell1:1-5": "ERROR Fact book-f01: book.ipynb#cell1 has 3 lines; line 5 is out of range.",
             "book.ipynb:1": 'ERROR Fact book-f01: "book.ipynb:1": a notebook anchor needs a zero-based cell, like '
                             "book.ipynb#cell0:1.",
             "helper.py#cell0:1": 'ERROR Fact book-f01: "helper.py#cell0:1": only notebooks (.ipynb) take #cellN.'}
    for locator, expected in cases.items():
        found = problems_of(shared_world, base.replace("Anchors: {}", f"Anchors: {locator}"), "pilot-book")
        assert expected in found, (locator, found)
    fine = problems_of(shared_world, base.replace("Anchors: {}", "Anchors: book.ipynb#cell1:1-3; book.ipynb#cell2:1"),
                       "pilot-book")
    assert not [line for line in fine if line.startswith("ERROR")]


def test_added_items_and_defects(shared_world: wd.World) -> None:
    marker = "## Disagreements"
    text = accept_all(shared_world, "pilot-demo")
    good = insert_before(text, marker, [
        "## Added fact demo-h01", "Wording: A synthetic added fact.", "Basis: observed", "Essential: yes",
        "Anchors: train.py:30-31", "Reason: synthetic", "",
        "## Added fact demo-h02", "Wording: An unresolved synthetic fact.", "Basis: unresolved", "Essential: no",
        "Reason: synthetic", "",
        "## Added unknown demo-hu01", "Wording: A synthetic added unknown.", "Runs must state: yes", "Reason: synthetic",
        "",
        "## Defect demo-d01", "Wording: A synthetic defect.", "Severity: medium", "Anchors: lib/model.py:4",
        "Counter-evidence: none found (synthetic)", "Reason: synthetic", ""])
    assert not [line for line in problems_of(shared_world, good) if not line.startswith("TODO  Task")]
    result = wd.check_reference(shared_world, complete(good).encode("utf-8"), "pilot-demo.md")
    assert result.ready
    assert [fact["id"] for fact in result.facts if fact["essential"]] == ["demo-f01", "demo-f03", "demo-h01"]
    assert result.facts[-1]["anchors"] == [] and result.facts[-2]["anchors"] == [
        {"id": "demo-h01-a1", "file": "train.py", "line": 30, "endLine": 31}]
    bad = insert_before(text, marker, [
        "## Added fact demo-x1", "Wording: Bad.", "Basis: observed", "Essential: yes", "Reason: synthetic", "",
        "## Added unknown demo-u9", "Wording: Bad.", "Reason: synthetic", "",
        "## Defect demo-d1", "Wording: Bad.", "Severity: huge", "Anchors: lib/model.py:4", "Reason: synthetic", "",
        "## Defect demo-d02", "Wording: A high synthetic defect.", "Severity: high", "Anchors: lib/model.py:5",
        "Counter-evidence: none (synthetic)", "Reason: synthetic", "",
        "## Fact demo-f99", "Decision: accept", ""])
    found = problems_of(shared_world, bad)
    for expected in ["ERROR Added fact demo-x1: added fact IDs look like demo-h01, demo-h02, ...",
                     'ERROR Added fact demo-x1: "Anchors:" is required unless Basis is unresolved.',
                     "ERROR Added unknown demo-u9: added unknown IDs look like demo-hu01, demo-hu02, ...",
                     'ERROR Added unknown demo-u9: "Runs must state:" is missing.',
                     "ERROR Defect demo-d1: defect IDs look like demo-d01, demo-d02, ...",
                     'ERROR Defect demo-d1: "Counter-evidence:" is missing.',
                     'ERROR Defect demo-d1: "Severity: huge" must be high, medium or low.',
                     "NOTE  Defect demo-d02: a second reviewer is recommended for high-severity defects (REVIEW_GUIDE).",
                     'ERROR Fact demo-f99: "demo-f99" is not an item of pilot-demo.json. Added items use '
                     '"## Added fact demo-h01". The lines under this heading, up to the next one, belong to it, not '
                     'to the section above it; put ">" in front of notes.']:
        assert expected in found, (expected, found)


def test_header_sections_and_task_rules(shared_world: wd.World) -> None:
    text = complete(accept_all(shared_world, "pilot-demo"))
    edited = re.sub(r"Candidate: pilot-demo\.json ([0-9a-f]{64})", "Candidate: pilot-demo.json " + "0" * 64, text)
    digest = er.sha256_bytes((shared_world.root / "evals/workflow/reference-candidates/pilot-demo.json").read_bytes())
    assert problems_of(shared_world, edited) == [
        f'ERROR header: the Candidate line must read "pilot-demo.json {digest[:12]}..."; restore the line the tool '
        "wrote (candidate ledgers are immutable)."]
    dated = text.replace(f"Date: {DATE}", "Date: 2026-02-30")
    assert problems_of(shared_world, dated) == ['ERROR header: "2026-02-30" is not a date. Use YYYY-MM-DD.']
    transcribed = text.replace("Transcribed by:\n", "Transcribed by: Synthetic Assistant\n")
    assert problems_of(shared_world, transcribed) == [
        'NOTE  header: transcribed by Synthetic Assistant; the reviewer must read the whole file before writing '
        '"Review: complete".']
    lines = text.split("\n")
    start = lines.index("## Fact demo-f02")
    removed = "\n".join(lines[:start] + lines[start + 5:])
    assert problems_of(shared_world, removed) == [
        "ERROR Fact demo-f02: this section is missing; restore it from the template (python tools/workflow_eval.py "
        "template --show pilot-demo)."]
    doubled = insert_before(text, "## Disagreements", lines[start:start + 5])
    found = problems_of(shared_world, doubled)
    assert found == [f"ERROR Fact demo-f02: this section appears twice (first on line {start + 1}). Keep one."]
    pending = text.replace("Decision: accept\n\n## Fact demo-f02", "Decision: pending\n\n## Fact demo-f02")
    assert problems_of(shared_world, pending) == ["TODO  Fact demo-f01: Decision is still pending.",
                                                  "ERROR Task: Review is complete, but 1 item(s) above are still to do."]
    assert problems_of(shared_world, text.replace("Review: complete", "Review: done")) == [
        'ERROR Task: "Review: done" must be pending or complete.']
    stray = text.replace("## Disagreements\n", "## Disagreements\ndemo-f01: we agreed\n")
    assert problems_of(shared_world, stray) == [
        'ERROR Disagreements: "demo-f01": there is no second review (pilot-demo.second.md) to disagree with; delete '
        "this line."]
    assert problems_of(shared_world, text.replace("Decision: accept\n\n## Fact demo-f01", "\n## Fact demo-f01")) == [
        'ERROR Scenario: the "Decision:" line is missing.']
    note = text.replace("## Fact demo-f01\n", "## Fact demo-f01\nA free note\n")
    assert problems_of(shared_world, note) == ['ERROR Fact demo-f01: "A free note" is not "Key: value". Put ">" in front '
                                               "of notes."]


def test_placeholder_scenario_must_be_replaced(tmp_path: Path) -> None:
    world = make_world(tmp_path, placeholder=True)
    text = accept_all(world, "pilot-book", runs="yes")
    found = problems_of(world, text, "pilot-book")
    assert 'ERROR Scenario: the proposed arguments contain a placeholder (<...>); write "Decision: replace" and give ' \
           "concrete Arguments." in found
    replaced = in_section(text, "Scenario", "Decision: accept", [
        "Decision: replace", "Description: Read the synthetic notebook with work directory ./work (synthetic).",
        "Entrypoints: book.ipynb", "Arguments: --workdir=./work", "Reason: a concrete directory (synthetic)"])
    assert [line for line in problems_of(world, replaced, "pilot-book") if line.startswith("ERROR")] == []


# --------------------------------------------------------------------------------------------
# Second review and disagreements


def test_second_review_disagreement_and_resolution(tmp_path: Path, verified) -> None:
    world = make_world(tmp_path)
    primary = accept_all(world, "pilot-demo")
    primary = in_section(primary, "Fact demo-f01", "Decision: accept",
                         ["Decision: qualify", "Wording: Forty micro-steps without data parallelism (synthetic).",
                          "Reason: synthetic"])
    second = fill_header(wd.task_template(world, "pilot-demo", second=True), SECOND)
    second = decide(second, "Fact demo-f01", "reject", "Reason: synthetic")
    second = decide(second, "Fact demo-f02", "accept", "Essential: yes", "Reason: synthetic")
    write(world, "pilot-demo.second.md", second)
    write(world, "pilot-demo.md", complete(primary))
    code, out = run(world, "check", "pilot-demo")
    lines = out.splitlines()
    disagreements = [line for line in lines if "Disagreements:" in line]
    assert disagreements == [
        f"evals/workflow/decisions/pilot-demo.md:{primary.split(chr(10)).index('## Disagreements') + 1}: TODO  "
        f"Disagreements: demo-f01: the second reviewer ({SECOND}) chose reject; you chose qualify. Add "
        '"demo-f01: <how it was resolved>".',
        f"evals/workflow/decisions/pilot-demo.md:{primary.split(chr(10)).index('## Disagreements') + 1}: TODO  "
        f"Disagreements: demo-f02: the second reviewer ({SECOND}) chose accept (essential: yes); you chose accept "
        '(essential: no). Add "demo-f02: <how it was resolved>".']
    # A second review merged after the owner's "Review: complete" leaves to-dos, never an error (HONEST-F3).
    assert "pilot-demo: 0 error(s), 3 to do; in progress." in lines, lines
    assert any("TODO  Task: Review is complete, but the second review added 2 item(s) to resolve under ## "
               "Disagreements." in line for line in lines), lines
    assert "pilot-demo (second review): 0 error(s), 1 to do; in progress." in lines
    assert not [line for line in lines if "pilot-demo.second.md" in line and "Decision is still pending" in line]
    resolved = primary.replace("## Disagreements\n", "## Disagreements\ndemo-f01: kept the qualification after "
                                                     "discussion (synthetic)\ndemo-f02: kept not essential (synthetic)\n"
                                                     "demo-f03: nothing to resolve\n")
    write(world, "pilot-demo.md", complete(resolved))
    code, out = run(world, "check", "pilot-demo")
    assert code == 1
    assert [line.split(": ", 1)[1] for line in out.splitlines() if "ERROR" in line] == [
        'ERROR Disagreements: "demo-f03" does not disagree with the second review; delete this line.']
    resolved = resolved.replace("demo-f03: nothing to resolve\n", "")
    write(world, "pilot-demo.md", complete(resolved))
    write(world, "pilot-demo.second.md", complete(second))
    code, out = run(world, "check", "pilot-demo")
    assert code == 0 and "pilot-demo: 0 error(s), 0 to do; ready to freeze." in out
    assert "pilot-demo (second review): 0 error(s), 0 to do; ready to freeze." in out
    write(world, "pilot-book.md", complete(accept_all(world, "pilot-book", runs="yes")))
    write(world, "run-policy.md", fill_policy(world))
    code, out = run(world, "freeze", "--campaign", "pilot-99", "--write", "--frozen-at", FROZEN_AT)
    assert code == 0, out
    frozen = json.loads((world.root / "evals/workflow/pilot/pilot-99/reference/pilot-demo.json").read_text(encoding="utf-8"))
    assert [review["role"] for review in frozen["reviews"]] == ["primary", "second"]
    assert frozen["reviews"][1]["reviewer"] == SECOND
    assert frozen["disputes"] == [
        {"item": "demo-f01", "primary": {"decision": "qualify", "basis": "observed", "essential": True},
         "second": {"decision": "reject"}, "resolution": "kept the qualification after discussion (synthetic)"},
        {"item": "demo-f02", "primary": {"decision": "accept", "basis": "observed", "essential": False},
         "second": {"decision": "accept", "basis": "observed", "essential": True},
         "resolution": "kept not essential (synthetic)"}]
    freeze_json = json.loads((world.root / "evals/workflow/pilot/pilot-99/freeze.json").read_text(encoding="utf-8"))
    assert "evals/workflow/decisions/pilot-demo.second.md" in freeze_json["decisionFiles"]


def test_a_second_review_must_carry_its_own_title(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    write(world, "pilot-demo.md", accept_all(world, "pilot-demo"))
    for wrong in (wd.task_template(world, "pilot-demo"), wd.task_template(world, "pilot-book", second=True)):
        write(world, "pilot-demo.second.md", wrong)
        code, out = run(world, "check", "pilot-demo")
        assert code == 1
        second = [line for line in out.splitlines() if line.startswith("evals/workflow/decisions/pilot-demo.second.md")]
        assert any('ERROR header: a second review must start with "# Second review: pilot-demo".' in line
                   for line in second), out
        assert "Disagreements:" not in out


def test_high_severity_note_is_satisfied_by_a_second_review(shared_world: wd.World) -> None:
    defect = ["## Defect demo-d01", "Wording: A high synthetic defect.", "Severity: high", "Anchors: lib/model.py:5",
              "Counter-evidence: none (synthetic)", "Reason: synthetic", ""]
    primary = insert_before(accept_all(shared_world, "pilot-demo"), "## Disagreements", defect)
    theirs = [line.replace("demo-d01", "demo-s-d01") for line in defect]
    second = insert_before(fill_header(wd.task_template(shared_world, "pilot-demo", second=True), SECOND), "## Task",
                           theirs)
    second_check = wd.check_reference(shared_world, second.encode("utf-8"), "pilot-demo.second.md")
    assert second_check.errors == 0, [p.message for p in second_check.report.problems]
    with_second = wd.check_reference(shared_world, primary.encode("utf-8"), "pilot-demo.md", second=second_check)
    alone = wd.check_reference(shared_world, primary.encode("utf-8"), "pilot-demo.md")
    assert [p.message for p in alone.report.problems if p.level == "NOTE"] == [
        "a second reviewer is recommended for high-severity defects (REVIEW_GUIDE)."]
    # A second review cannot hold a position on the primary's own demo-d01, so it keeps a NOTE (OWNERUX2-3) ...
    # It names an unused ID, and mentions the unresolved demo-s-d01 only as a possible match (OWNERUX4-2).
    notes = [p.message for p in with_second.report.problems if p.level == "NOTE"]
    assert notes == ['the second review does not cover your own additions. For a second opinion on this high-severity '
                     'defect, the second reviewer adds it as "## Defect demo-s-d02" and you resolve it as "demo-s-d02: '
                     'adopted as demo-d01 -- <why>"; otherwise it is not second-reviewed (REVIEW_GUIDE). If demo-s-d01 '
                     'is the same defect, resolve it as "<ID>: adopted as demo-d01 -- <why>" instead.'], notes
    # ... resolving an unrelated addition as not adopted keeps it, and only adopting the matching addition clears it.
    rejected = primary.replace("## Disagreements\n", "## Disagreements\ndemo-s-d01: not a defect (synthetic)\n")
    checked = wd.check_reference(shared_world, rejected.encode("utf-8"), "pilot-demo.md", second=second_check)
    notes = [p.message for p in checked.report.problems if p.level == "NOTE"]
    assert len(notes) == 1 and '"## Defect demo-s-d02"' in notes[0] and "demo-s-d01" not in notes[0], notes
    assert not [p for p in checked.report.problems if p.section == "Disagreements"]
    adopted = primary.replace("## Disagreements\n", "## Disagreements\ndemo-s-d01: adopted as demo-d01 -- the same "
                                                    "defect (synthetic)\n")
    checked = wd.check_reference(shared_world, adopted.encode("utf-8"), "pilot-demo.md", second=second_check)
    assert [p.level for p in checked.report.problems].count("NOTE") == 0 and checked.errors == 0
    assert not [p for p in checked.report.problems if p.section == "Disagreements"]
    assert checked.disputes[0]["adoptedAs"] == "demo-d01"
    assert checked.disputes[0]["primary"] == {"decision": "added", "severity": "high"}


def test_the_second_reviewers_own_additions_must_be_resolved(tmp_path: Path, verified) -> None:
    world = make_world(tmp_path)
    added = ["## Added fact demo-s-h01", "Wording: The synthetic loop also clips gradients at one.",
             "Basis: observed", "Essential: yes", "Anchors: train.py:10", ""]
    second = insert_before(fill_header(wd.task_template(world, "pilot-demo", second=True), SECOND), "## Task", added)
    primary = accept_all(world, "pilot-demo")
    write(world, "pilot-demo.second.md", complete(second))
    write(world, "pilot-demo.md", complete(primary))
    code, out = run(world, "check", "pilot-demo")
    assert code == 1
    assert f'TODO  Disagreements: demo-s-h01: the second reviewer ({SECOND}) added the fact "The synthetic loop also ' \
           'clips gradients at one." (basis: observed, essential: yes). To adopt it, add it under your own ID and write ' \
           '"demo-s-h01: adopted as <your ID> -- <why>"; otherwise write "demo-s-h01: <why it is not adopted>".' in out, out
    resolved = primary.replace("## Disagreements\n", "## Disagreements\ndemo-s-h01: not supported by the source "
                                                     "(synthetic)\n")
    write(world, "pilot-demo.md", complete(resolved))
    code, out = run(world, "check", "pilot-demo")
    assert "pilot-demo: 0 error(s), 0 to do; ready to freeze." in out, out
    result = wd.check_path(world, world.root / wd.DECISIONS_REL / "pilot-demo.md")[0].result
    assert result.disputes == [{"item": "demo-s-h01", "primary": None,
                                "second": {"decision": "added", "basis": "observed", "essential": True},
                                "resolution": "not supported by the source (synthetic)"}], result.disputes


def test_an_adopted_addition_is_linked_to_the_primary_id(tmp_path: Path, verified) -> None:
    """ "adopted as <your ID>" records the adopting item, so summaries count it inside the denominators (OWNERUX2-2)."""
    world = make_world(tmp_path)
    added = ["## Added fact demo-s-h01", "Wording: The synthetic loop also clips gradients at one.",
             "Basis: observed", "Essential: yes", "Anchors: train.py:10", "", "## Added unknown demo-s-hu01",
             "Wording: The synthetic seed is not fixed.", "Runs must state: yes", ""]
    second = insert_before(fill_header(wd.task_template(world, "pilot-demo", second=True), SECOND), "## Task", added)
    write(world, "pilot-demo.second.md", complete(second))
    own = ["## Added fact demo-h01", "Wording: The synthetic loop clips gradients at one.", "Basis: observed",
           "Essential: yes", "Anchors: train.py:10", "Reason: adopted from the second review (synthetic)", "",
           "## Added unknown demo-hu01", "Wording: The synthetic seed is not fixed.", "Runs must state: yes",
           "Reason: adopted from the second review (synthetic)", ""]
    primary = insert_before(accept_all(world, "pilot-demo"), "## Disagreements", own)
    wrong = primary.replace("## Disagreements\n", "## Disagreements\ndemo-s-h01: adopted as demo-hu01 -- (synthetic)\n"
                                                  "demo-s-hu01: adopted -- same unknown (synthetic)\n")
    write(world, "pilot-demo.md", complete(wrong))
    code, out = run(world, "check", "pilot-demo")
    assert code == 1
    assert 'ERROR Disagreements: demo-s-h01: "adopted as demo-hu01" must name the section you added for it in this ' \
           'file, "## Added fact demo-h01"; write "demo-s-h01: adopted as <your ID> -- <why>".' in out, out
    assert 'ERROR Disagreements: demo-s-hu01: "adopted" must name the section you added for it in this file, ' \
           '"## Added unknown demo-hu01"' in out, out
    resolved = primary.replace("## Disagreements\n", "## Disagreements\ndemo-s-h01: adopted as demo-h01 (synthetic)\n"
                                                     "demo-s-hu01: Adopted as demo-hu01. -- the same unknown (synthetic)\n")
    write(world, "pilot-demo.md", complete(resolved))
    code, out = run(world, "check", "pilot-demo")
    assert "pilot-demo: 0 error(s), 0 to do; ready to freeze." in out, out
    result = wd.check_path(world, world.root / wd.DECISIONS_REL / "pilot-demo.md")[0].result
    assert result.disputes == [
        {"item": "demo-s-h01", "primary": {"decision": "added", "basis": "observed", "essential": True},
         "second": {"decision": "added", "basis": "observed", "essential": True}, "adoptedAs": "demo-h01",
         "resolution": "adopted as demo-h01 (synthetic)"},
        {"item": "demo-s-hu01", "primary": {"decision": "added", "runsMustState": True},
         "second": {"decision": "added", "runsMustState": True}, "adoptedAs": "demo-hu01",
         "resolution": "Adopted as demo-hu01. -- the same unknown (synthetic)"}], result.disputes


def test_a_wrapped_resolution_is_told_to_indent(tmp_path: Path, verified) -> None:
    """A resolution's wrapped second line that contains ": " is not advised to be deleted (OWNERUX2-6)."""
    world = make_world(tmp_path)
    second = decide(fill_header(wd.task_template(world, "pilot-demo", second=True), SECOND), "Fact demo-f01", "reject",
                    "Reason: synthetic")
    write(world, "pilot-demo.second.md", complete(second))
    primary = accept_all(world, "pilot-demo")
    wrapped = primary.replace("## Disagreements\n", "## Disagreements\ndemo-f01: kept accept; we discussed that the "
                                                    "second reviewer read\nthe DDP branch: lines 94-95 only apply under "
                                                    "DDP (synthetic)\n")
    write(world, "pilot-demo.md", complete(wrapped))
    code, out = run(world, "check", "pilot-demo")
    assert code == 1
    assert 'ERROR Disagreements: "the DDP branch" is not an item ID. To continue the previous line, indent it by two ' \
           'spaces; put ">" in front of notes only.' in out, out
    write(world, "pilot-demo.md", complete(wrapped.replace("\nthe DDP branch:", "\n  the DDP branch:")))
    code, out = run(world, "check", "pilot-demo")
    assert "pilot-demo: 0 error(s), 0 to do; ready to freeze." in out, out
    result = wd.check_path(world, world.root / wd.DECISIONS_REL / "pilot-demo.md")[0].result
    assert result.disputes[0]["resolution"] == ("kept accept; we discussed that the second reviewer read the DDP branch: "
                                                "lines 94-95 only apply under DDP (synthetic)")


def test_a_second_review_by_the_primary_reviewer_is_an_error(tmp_path: Path, verified) -> None:
    world = make_world(tmp_path)
    second = fill_header(wd.task_template(world, "pilot-demo", second=True), " test  REVIEWER (synthetic) ")
    write(world, "pilot-demo.second.md", complete(second))
    write(world, "pilot-demo.md", complete(accept_all(world, "pilot-demo")))
    code, out = run(world, "check", "pilot-demo")
    assert code == 1
    assert 'ERROR header: a second review must be written by a different person than the primary reviewer (both ' \
           'files name "test  REVIEWER (synthetic)").' in out, out
    assert "pilot-demo (second review): 1 error(s), 0 to do; not ready (fix the errors)." in out


# --------------------------------------------------------------------------------------------
# Messages pinned by the specification against the real ledgers


SPEC_PARTIAL = """\
evals/workflow/decisions/pilot-nanogpt.md:35: ERROR Fact nanogpt-f03: unknown field "Essentail". Allowed here: Anchors, Basis, Decision, Essential, Reason, Wording.
evals/workflow/decisions/pilot-nanogpt.md:45: ERROR Fact nanogpt-f05: Decision is qualify but there is no "Wording:" line. Add "Wording: <your corrected claim>".
evals/workflow/decisions/pilot-nanogpt.md:52: ERROR Fact nanogpt-f06: "Decision: aprove" is not a decision. Write one of: accept, qualify, reject.
evals/workflow/decisions/pilot-nanogpt.md:57: ERROR Fact nanogpt-f07: Decision is reject but "Reason:" is missing. Say why the claim is wrong or not needed.
evals/workflow/decisions/pilot-nanogpt.md:58: ERROR Fact nanogpt-f07: a rejected fact cannot be essential; delete the Essential line or change the decision.
evals/workflow/decisions/pilot-nanogpt.md:64: ERROR Fact nanogpt-f08: Essential and Anchors differ from the proposal; add "Reason:" saying why.
evals/workflow/decisions/pilot-nanogpt.md:65: ERROR Fact nanogpt-f08: train.py has 336 lines; line 400 is out of range.
evals/workflow/decisions/pilot-nanogpt.md:65: NOTE  Fact nanogpt-f08: train.py:231-242 (proposed) is no longer an anchor: Anchors: replaces the proposed list, so repeat every proposed anchor you keep.
evals/workflow/decisions/pilot-nanogpt.md:70: TODO  Fact nanogpt-f09: Decision is still pending.
evals/workflow/decisions/pilot-nanogpt.md:75: TODO  Fact nanogpt-f10: Decision is still pending.
evals/workflow/decisions/pilot-nanogpt.md:79: TODO  Unknown nanogpt-u01: Decision is still pending.
evals/workflow/decisions/pilot-nanogpt.md:84: TODO  Unknown nanogpt-u02: Decision is still pending.
evals/workflow/decisions/pilot-nanogpt.md:90: TODO  Unknown nanogpt-u03: "Runs must state:" must be yes (every run must state this uncertainty) or no.
evals/workflow/decisions/pilot-nanogpt.md:94: TODO  Non-defect nanogpt-n01: Decision is still pending.
evals/workflow/decisions/pilot-nanogpt.md:98: TODO  Non-defect nanogpt-n02: Decision is still pending.
evals/workflow/decisions/pilot-nanogpt.md:102: TODO  Non-defect nanogpt-n03: Decision is still pending.
evals/workflow/decisions/pilot-nanogpt.md:108: ERROR Added fact nanogpt-x1: added fact IDs look like nanogpt-h01, nanogpt-h02, ...
evals/workflow/decisions/pilot-nanogpt.md:120: ERROR Task: Review is complete, but 8 item(s) above are still to do.
pilot-nanogpt: 9 error(s), 8 to do; not ready (fix the errors).
  facts decided: 5 accept, 1 qualify, 1 reject; essential so far (7): nanogpt-f01 nanogpt-f02 nanogpt-f03 nanogpt-f04 nanogpt-f05 nanogpt-f08 nanogpt-x1
"""
NANOGPT_DISPLAY = "evals/workflow/decisions/pilot-nanogpt.md"


def nanogpt_partial(world: wd.World) -> str:
    """The partly filled nanoGPT file of the specification (section 1.6), built from the pristine template."""
    text = fill_header(wd.task_template(world, "pilot-nanogpt"))
    text = decide(text, "Scenario", "accept")
    for ident in ("nanogpt-f01", "nanogpt-f02", "nanogpt-f04"):
        text = decide(text, f"Fact {ident}", "accept")
    text = decide(text, "Fact nanogpt-f03", "accept", "Essentail: no")
    text = decide(text, "Fact nanogpt-f05", "qualify", "Anchors: train.py:48-49; train.py:94-95",
                  "Reason: lines 94-95 divide the count by ddp_world_size")
    text = decide(text, "Fact nanogpt-f06", "aprove")
    text = decide(text, "Fact nanogpt-f07", "reject", "Essential: yes")
    text = decide(text, "Fact nanogpt-f08", "accept", "Essential: yes", "Anchors: train.py:231-400")
    text = decide(text, "Unknown nanogpt-u03", "accept")
    text = insert_before(text, "## Disagreements", [
        "## Added fact nanogpt-x1", "Wording: The optimizer is AdamW with fused kernels when available.",
        "Basis: observed", "Essential: yes", "Anchors: model.py:263-280", "Reason: needed for the update step", ""])
    return complete(text)


def render(world: wd.World, result: wd.RefCheck) -> str:
    return "".join(f"{p}\n" for p in result.report.ordered()) + "".join(f"{line}\n" for line in
                                                                         wd.reference_summary(world, result))


@needs_corpus
def test_specification_partial_file_output_verbatim_with_the_corpus() -> None:
    world = wd.World(ROOT, real_corpus())
    text = nanogpt_partial(world)
    assert len(text.split("\n")) == 121  # the specification's line numbers need the same layout
    result = wd.check_reference(world, text.encode("utf-8"), NANOGPT_DISPLAY)
    assert render(world, result) == SPEC_PARTIAL


def test_specification_partial_file_output_without_the_corpus() -> None:
    world = wd.World(ROOT, None)
    result = wd.check_reference(world, nanogpt_partial(world).encode("utf-8"), NANOGPT_DISPLAY)
    expected = [line for line in SPEC_PARTIAL.splitlines() if "336 lines" not in line]
    expected[-2] = "pilot-nanogpt: 8 error(s), 8 to do; not ready (fix the errors)."
    assert render(world, result).splitlines() == expected + ["  anchors not checked: corpus absent (freeze requires it)"]


def test_other_specification_messages_against_real_ledgers() -> None:
    world = wd.World(ROOT, None)
    pristine = wd.task_template(world, "pilot-nanogpt")
    digest = er.sha256_bytes((ROOT / "evals/workflow/reference-candidates/pilot-nanogpt.json").read_bytes())

    def messages(text: str, display: str = NANOGPT_DISPLAY) -> list[str]:
        return [str(p) for p in wd.check_reference(world, text.encode("utf-8"), display).report.ordered()
                if p.level != "TODO"]

    assert messages(pristine.replace(digest, "1" * 64)) == [
        f'{NANOGPT_DISPLAY}:9: ERROR header: the Candidate line must read "pilot-nanogpt.json 9dded969253e..."; restore '
        "the line the tool wrote (candidate ledgers are immutable)."]
    lines = pristine.split("\n")
    start = lines.index("## Fact nanogpt-f04")
    assert messages("\n".join(lines[:start] + lines[start + 5:])) == [
        f"{NANOGPT_DISPLAY}:1: ERROR Fact nanogpt-f04: this section is missing; restore it from the template "
        "(python tools/workflow_eval.py template --show pilot-nanogpt)."]
    f02 = lines.index("## Fact nanogpt-f02")
    doubled = insert_before(pristine, "## Disagreements", lines[f02:f02 + 5])
    assert messages(doubled) == [f"{NANOGPT_DISPLAY}:{doubled.split(chr(10)).index('## Disagreements') - 4}: ERROR "
                                 "Fact nanogpt-f02: this section appears twice (first on line 26). Keep one."]
    assert messages(pristine.replace("Transcribed by:\n", "Transcribed by: Synthetic Assistant\n")) == [
        f'{NANOGPT_DISPLAY}:12: NOTE  header: transcribed by Synthetic Assistant; the reviewer must read the whole file '
        'before writing "Review: complete".']
    flax = decide(wd.task_template(world, "pilot-flax"), "Scenario", "accept")
    assert messages(flax, "evals/workflow/decisions/pilot-flax.md") == [
        'evals/workflow/decisions/pilot-flax.md:19: ERROR Scenario: the proposed arguments contain a placeholder (<...>); '
        'write "Decision: replace" and give concrete Arguments.']


# --------------------------------------------------------------------------------------------
# Run policy


def policy_problems(world: wd.World, text: str) -> list[str]:
    result = wd.check_policy(world, text.encode("utf-8"), "run-policy.md")
    return [f"{p.level:<5} {p.section}: {p.message}" for p in result.report.ordered()]


def test_policy_pristine_and_complete(shared_world: wd.World) -> None:
    pristine = wd.policy_template(shared_world)
    result = wd.check_policy(shared_world, pristine.encode("utf-8"), "run-policy.md")
    assert (result.errors, result.todos) == (0, 2 + 3 * 2 + 1 + 3 + 2 + 2 + 1 + 1 + 1 + 1 + 1)
    assert wd.policy_summary(result) == ["run-policy: 0 error(s), 21 to do; in progress.",
                                         "  hosts filled: 0 of 2; prompts accepted: 0 of 2; targets: pending"]
    done = wd.check_policy(shared_world, fill_policy(shared_world, sessions="4").encode("utf-8"), "run-policy.md")
    assert done.ready and done.values["baselineSessions"] == 4 and done.values["perHostTargets"] is False
    assert wd.policy_summary(done)[0] == "run-policy: 0 error(s), 0 to do; ready to freeze."


POLICY_RULES = [
    ({"Active minutes:": "Active minutes: 0"}, 'ERROR Budget: "Active minutes: 0" must be a whole number from 1 to 240.'),
    ({"Repair rounds:": "Repair rounds: two"}, 'ERROR Budget: "Repair rounds: two" must be a whole number from 0 to 5.'),
    ({"Infrastructure retries:": "Infrastructure retries: 2"},
     'ERROR Budget: "Infrastructure retries: 2" must be a whole number from 0 to 1.'),
    ({"Qualified claims:": "Qualified claims: half"},
     'ERROR Scoring: "Qualified claims: half" must be one of: not-supported, supported, excluded.'),
    ({"Per-host targets:": "Per-host targets: sometimes"},
     'ERROR Scoring: "Per-host targets: sometimes" must be one of: yes, no.'),
    ({"Baseline sessions:": "Baseline sessions: 24"}, 'ERROR Conditions: "Baseline sessions: 24" must be one of: 4, 0.'),
    ({"Helper Python:": "Helper Python: /Users/someone/.venv/bin/python"},
     "ERROR Environment: Helper Python contains an absolute machine path (/Users/); describe it without one."),
    ({"Decision: pending": "Decision: amend"},
     'ERROR Targets: "Decision: amend" is not a decision. Write accept (to change a target, edit '
     "evals/workflow/tasks.json pilotTargets before the freeze)."),
]


@pytest.mark.parametrize("change, expected", POLICY_RULES)
def test_policy_rules(shared_world: wd.World, change: dict, expected: str) -> None:
    text = fill_policy(shared_world)
    (old, new), = change.items()
    base = fill_policy(shared_world, **{old: new}) if old != "Decision: pending" else \
        text.replace("## Targets\n", "## Targets\n", 1)
    if old == "Decision: pending":
        lines = text.split("\n")
        index = lines.index("## Targets")
        position = next(i for i in range(index, len(lines)) if lines[i] == "Decision: accept")
        lines[position] = new
        base = "\n".join(lines)
    assert expected in policy_problems(shared_world, base)


def test_policy_prompt_rules(shared_world: wd.World) -> None:
    text = fill_policy(shared_world)
    skill = wd.SKILL_PROMPT_PROPOSAL.split("\n")
    no_skill = wd.NO_SKILL_PROMPT_PROPOSAL.split("\n")

    def with_prompt(original: list[str], replacement: list[str]) -> list[str]:
        edited = text.replace("\n".join(original), "\n".join(replacement), 1)
        assert edited != text
        return policy_problems(shared_world, edited)

    found = with_prompt(skill, [line.replace("{artifact_path}", "the output") for line in skill])
    assert "ERROR Skill prompt: the skill prompt must contain {artifact_path}." in found
    found = with_prompt(skill, skill + ["Use {model}."])
    assert "ERROR Skill prompt: the prompt uses unknown placeholder(s) {model}; the placeholders are {task_prompt}, " \
           "{scenario} and {artifact_path}." in found
    found = with_prompt(skill, skill + ["Write to /home/someone/out."])
    assert "ERROR Skill prompt: the prompt contains an absolute machine path (/home/); prompts must not name machine " \
           "paths." in found
    found = with_prompt(no_skill, no_skill + ["Save {artifact_path} with the MLView skill as a WorkflowDocument in "
                                              "x.mlview.json."])
    for expected in ["ERROR No-skill prompt: the no-skill prompt must not contain {artifact_path}; a baseline "
                     "publishes nothing.",
                     'ERROR No-skill prompt: the no-skill prompt must not mention "MLView" (CANDIDATE_PROTOCOL.md, '
                     '"Frozen prompts").',
                     'ERROR No-skill prompt: the no-skill prompt must not mention "skill" (CANDIDATE_PROTOCOL.md, '
                     '"Frozen prompts").',
                     'ERROR No-skill prompt: the no-skill prompt must not mention "WorkflowDocument" '
                     '(CANDIDATE_PROTOCOL.md, "Frozen prompts").',
                     'ERROR No-skill prompt: the no-skill prompt must not mention ".mlview.json" '
                     '(CANDIDATE_PROTOCOL.md, "Frozen prompts").']:
        assert expected in found, (expected, found)
    found = with_prompt(no_skill, no_skill + ["Then publish the result."])
    assert 'ERROR No-skill prompt: the no-skill prompt must not mention "publish" (CANDIDATE_PROTOCOL.md, "Frozen ' \
           'prompts").' in found
    found = with_prompt(no_skill, [line.replace("{scenario}", "the scenario") for line in no_skill])
    assert "ERROR No-skill prompt: the no-skill prompt must contain {scenario}." in found
    unfenced = text.replace("```text\n" + "\n".join(no_skill) + "\n```\n", "")
    assert "ERROR No-skill prompt: the prompt text must be a fenced block (```text ... ```); restore it from the " \
           "template." in policy_problems(shared_world, unfenced)
    extra_host = text.replace("## Environment", "## Host robot\nModel: x\n\n## Environment")
    assert 'ERROR Host robot: "robot" is not a host in evals/workflow/tasks.json (codex, copilot).' in \
        policy_problems(shared_world, extra_host)
    missing = text.replace("## Privacy", "## Privacy-gone")
    assert any(line.startswith('ERROR Privacy-gone: unknown section') for line in policy_problems(shared_world, missing))


def test_show_prompts_renders_every_prompt(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    write(world, "run-policy.md", fill_policy(world))
    replaced = in_section(accept_all(world, "pilot-demo"), "Scenario", "Decision: accept", [
        "Decision: replace", "Description: Inspect train.py and configs/a.py (synthetic).",
        "Entrypoints: train.py; configs/a.py", "Arguments: --config configs/a.py", "Reason: synthetic"])
    write(world, "pilot-demo.md", replaced)
    code, out = run(world, "check", "run-policy", "--show-prompts")
    assert code == 0
    assert "===== prompts/skill/pilot-demo.txt (scenario: replaced) =====" in out
    assert "===== prompts/baseline/pilot-book.txt (scenario: proposal; the decisions file does not exist) =====" in out
    assert "Entrypoints: train.py, configs/a.py\nArguments: --config configs/a.py\n" in out
    assert out.rstrip().endswith("4 prompts rendered; 0 leak finding(s).")


# --------------------------------------------------------------------------------------------
# Development adjudication (real, immutable ledgers; the verdicts are synthetic and stay in tmp)


def adjudication_problems(text: str) -> tuple[wd.AdjudicationCheck, list[str]]:
    world = wd.World(ROOT, None)
    result = wd.check_adjudication(world, text.encode("utf-8"), "development-adjudication.md")
    return result, [f"{p.level:<5} {p.section}: {p.message}" for p in result.report.ordered()]


def test_adjudication_messages() -> None:
    world = wd.World(ROOT, None)
    text = wd.adjudication_template(world)
    result, found = adjudication_problems(text)
    assert (result.errors, result.todos) == (0, 186)
    ledger = json.loads((ROOT / "evals/workflow/development/native-reviews/codex/dev-gan.json").read_text(encoding="utf-8"))
    digest = er.sha256_bytes((ROOT / "evals/workflow/development/native-reviews/codex/dev-gan.json").read_bytes())
    losses = ledger["usability"]["losses"]["status"]
    other = next(v for v in wd.USABILITY_VERDICTS if v != losses)
    edited = fill_header(text).replace(f"native-reviews/codex/dev-gan.json {digest}",
                                       "native-reviews/codex/dev-gan.json " + "0" * 64)
    edited = edited.replace("## dev-gan / codex\n", "## dev-gan / codex\n", 1)
    section = edited.split("## dev-gan / codex\n", 1)
    body = section[1].replace("usability.losses: pending", f"usability.losses: {other}", 1)
    body = body.replace("alternating-cycle: pending", "alternating-cycle: supported", 1)
    body = body.replace("running-loss-report: pending", "running-loss-report: aprove", 1)
    body = body.replace("epoch-outputs: pending", "epoch-outputs: supported node:x", 1)
    edited = section[0] + "## dev-gan / codex\n" + body
    edited = edited.replace("## Baselines\n", "## Baselines\n", 1).replace("\ncodex: pending\n", "\ncodex: corrected\n")
    edited = edited.replace("\ncopilot: pending\n", "\ncopilot: corrected " + EM + " the summary overstates coverage "
                                                                                   "(synthetic)\n")
    result, found = adjudication_problems(edited)
    for expected in [
            "ERROR dev-gan / codex: the Ledger line does not match native-reviews/codex/dev-gan.json (ledgers are "
            "immutable); restore the line the tool wrote.",
            f'ERROR dev-gan / codex: "usability.losses: {other}" differs from the provisional "{losses}"; add " -- '
            f'<reason>" (or " {EM} <reason>").',
            "TODO  dev-gan / codex: optimizer-ownership is still pending.",
            'ERROR dev-gan / codex: running-loss-report: "aprove" is not one of: omitted, qualified, supported, '
            "unsupported.",
            f'ERROR dev-gan / codex: epoch-outputs: write the verdict and an optional " -- <reason>" (or " {EM} '
            f'<reason>"); "node:x" is not expected.',
            f'ERROR Baselines: "codex: corrected" needs a reason; add " -- <reason>" (or " {EM} <reason>").']:
        assert expected in found, (expected, found)
    summary = wd.adjudication_summary(result)
    assert summary[0] == f"development-adjudication: {result.errors} error(s), {result.todos} to do; not ready (fix the errors)."
    assert "  dev-gan / codex: 1 of 9 claims, 0 of 6 usability decided; 1 agrees with the provisional label." in summary
    assert "  baselines: 1 decided" in summary
    hyphen = fill_header(text).replace("\ncodex: pending\n", "\ncodex: corrected - the summary overstates (synthetic)\n")
    assert 'ERROR Baselines: codex: Write the reason after " -- " (two hyphens) or " ' + EM + ' "; a single "-" is not ' \
           'a separator.' in adjudication_problems(hyphen)[1]
    glued = fill_header(text).replace("\ncodex: pending\n", "\ncodex: corrected--overstated (synthetic)\n")
    assert any('Put a space on both sides of the " -- "' in line for line in adjudication_problems(glued)[1])
    double = fill_header(text).replace("\ncodex: pending\n", "\ncodex: corrected -- the summary overstates (synthetic)\n")
    assert not [line for line in adjudication_problems(double)[1] if line.startswith("ERROR Baselines")]
    unknown = text.replace("optimizer-ownership: pending", "optimizer-ownership: pending\nno-such-claim: supported", 1)
    assert any("\"no-such-claim\" is not a claim of native-reviews/" in line for line in adjudication_problems(unknown)[1])
    first_claim = text.split("\n")[text.split("\n").index("## dev-config / copilot") + 4]
    dropped = text.replace("\n" + first_claim + "\n", "\n", 1)
    assert any(line.endswith("restore its line from the template (python tools/workflow_eval.py template --show "
                             "development-adjudication).") for line in adjudication_problems(dropped)[1])


def test_complete_adjudication_prints_confusion_tables() -> None:
    world = wd.World(ROOT, None)
    lines = []
    provisional: dict[str, str] = {}
    for line in fill_header(wd.adjudication_template(world)).split("\n"):
        match = re.match(r"> (\S+) \(provisional: (\w+)\)", line)
        if match:
            provisional[match.group(1)] = match.group(2)
        pending = re.match(r"(\S+): pending$", line)
        if pending and pending.group(1) != "Review":
            key = pending.group(1)
            if key in provisional:
                line = f"{key}: {provisional.pop(key)}"
            else:
                line = f"{key}: confirmed"
        lines.append(line)
    text = complete("\n".join(lines))
    result, found = adjudication_problems(text)
    assert found == [] and result.complete
    summary = wd.adjudication_summary(result)
    assert summary[0] == "development-adjudication: 0 error(s), 0 to do; complete."
    assert "  Development evidence; not a held-out pilot result." in summary
    assert "  claims (rows: provisional, columns: human)" in summary
    assert summary[-1].startswith("  baselines: copilot confirmed; codex confirmed; claude-code confirmed")
    assert sum(result.confusion["claims"].values()) == 108 and sum(result.confusion["usability"].values()) == 72
    assert all(prior == human for prior, human in result.confusion["claims"])


# --------------------------------------------------------------------------------------------
# Check command routing


def test_check_routes_session_and_run_review_titles(tmp_path: Path, monkeypatch) -> None:
    world = make_world(tmp_path)
    session = tmp_path / "session.md"
    session.write_text("# Session: pilot-demo:codex:1\nStatus: pending\n", encoding="utf-8")
    monkeypatch.delitem(sys.modules, "workflow_pilot", raising=False)
    if not (wd.TOOLS / "workflow_pilot.py").is_file():
        code, out = run(world, "check", str(session))
        assert code == 1 and "Session files are checked by tools/workflow_pilot.py, which is not available in this " \
                             "build." in out
    fake = types.ModuleType("workflow_pilot")
    fake.__file__ = str(wd.TOOLS / "workflow_pilot.py")
    seen: list[tuple[Path, Path | None]] = []

    def check_file(path: Path, *, root: Path | None = None) -> list[er.Problem]:
        seen.append((Path(path), root))
        return [er.Problem(str(path), 2, er.TODO, "header", "Status is still pending (synthetic).")]

    fake.check_file = check_file
    monkeypatch.setitem(sys.modules, "workflow_pilot", fake)
    code, out = run(world, "check", str(session))
    assert code == 0 and seen == [(session, world.root)]  # a run review resolves its campaign in this checkout
    assert out.splitlines()[-1] == "session.md: 0 error(s), 1 to do; in progress."
    assert run(world, "check", "pilot-missing")[0] == 2
    assert run(world, "check", "pilot-demo")[0] == 2  # the decisions file does not exist yet


def test_check_without_targets_checks_every_file_and_never_writes(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    write(world, "pilot-demo.md", wd.task_template(world, "pilot-demo"))
    write(world, "pilot-book.md", wd.task_template(world, "pilot-book"))
    write(world, "run-policy.md", wd.policy_template(world))
    (world.root / wd.DECISIONS_REL / "README.md").write_text("# Owner decisions\n", encoding="utf-8")
    before = {path: path.read_bytes() for path in world.root.rglob("*") if path.is_file()}
    code, out = run(world, "check")
    assert code == 0
    assert [line for line in out.splitlines() if line and not line.startswith((" ", "evals/"))] == [
        "pilot-book: 0 error(s), 6 to do; in progress.", "pilot-demo: 0 error(s), 10 to do; in progress.",
        "run-policy: 0 error(s), 21 to do; in progress."]
    assert {path: path.read_bytes() for path in world.root.rglob("*") if path.is_file()} == before


# --------------------------------------------------------------------------------------------
# Context sheet


def test_context_sheet(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    code, out = run(world, "context", "pilot-demo")
    sheet = world.root / ".mlview/review-context/pilot-demo.md"
    assert code == 0 and "wrote .mlview/review-context/pilot-demo.md (3 facts, 4 anchors, all quotes verified)" in out
    text = sheet.read_text(encoding="utf-8")
    assert "### Anchor demo-a01: train.py:10-11 (quote verified against the pinned bytes)" in text
    assert "> 10 | value_10 = 10" in text and "   5 | value_5 = 5" in text and "  16 | value_16 = 16" in text
    assert "   4 | value_4 = 4" not in text
    assert "third-party source shown for review only" in text
    code, out = run(world, "context", "pilot-book")
    assert code == 0 and "> 1 | x = 1" in (world.root / ".mlview/review-context/pilot-book.md").read_text(encoding="utf-8")
    ledger_path = world.root / "evals/workflow/reference-candidates/pilot-demo.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["facts"][0]["anchors"][0]["quote"] = "value_10 = 11\nvalue_11 = 11"
    write_json(ledger_path, ledger)
    code, out = run(world, "context", "pilot-demo")
    assert code == 1 and "QUOTE MISMATCH" in sheet.read_text(encoding="utf-8")
    assert "mismatch: demo-a01 (train.py:10-11): the candidate quote differs from the pinned bytes" in out
    assert run(world, "context", "pilot-demo", corpus=None)[0] == 2


# --------------------------------------------------------------------------------------------
# Freeze


def frozen_dir(world: wd.World, campaign: str = "pilot-99") -> Path:
    return world.root / "evals/workflow/pilot" / campaign


def all_files(directory: Path) -> dict[str, bytes]:
    return {path.relative_to(directory).as_posix(): path.read_bytes() for path in sorted(directory.rglob("*"))
            if path.is_file()}


def test_freeze_dry_run_and_write(tmp_path: Path, verified) -> None:
    world = make_world(tmp_path)
    complete_world(world)
    tasks_before = (world.root / "evals/workflow/tasks.json").read_bytes()
    code, out = run(world, "freeze", "--campaign", "pilot-99", "--frozen-at", FROZEN_AT)
    assert code == 0, out
    assert out.splitlines() == [
        "Ready to freeze pilot-99 (dry run; nothing written)",
        "  task                facts  essential  rejected  added  runs-must-state  reviewers",
        f"  pilot-demo              3          2         0      0                0  {REVIEWER}",
        f"  pilot-book              1          1         0      0                1  {REVIEWER}",
        "  total                   4          3         0      0                1",
        f"  run policy: ready ({REVIEWER}, {DATE}); prompts: 4 rendered, 0 leak findings",
        "Would write evals/workflow/pilot/pilot-99/ (2 references, reference-set.json, policy.json, 4 prompts, freeze.json)",
        "Would update evals/workflow/tasks.json: 2 held-out referenceStatus -> frozen; add pilotFreeze",
        "Re-run with --write. Frozen files are created exclusively and never overwritten."]
    assert not frozen_dir(world).exists() and (world.root / "evals/workflow/tasks.json").read_bytes() == tasks_before
    assert sorted(verified) == ["book", "demo"]
    code, out = run(world, "freeze", "--campaign", "pilot-99", "--write", "--frozen-at", FROZEN_AT)
    assert code == 0, out
    assert out.splitlines()[-1] == ("Next: commit evals/workflow/decisions, evals/workflow/pilot/pilot-99 and "
                                    "evals/workflow/tasks.json together, before editing any of them again (until then "
                                    "Git does not hold the frozen bytes), and merge that commit into main with a merge "
                                    "commit or a fast-forward, never a squash or rebase merge. The freeze records the "
                                    "reviewers' decisions; it does not add an approval.")
    files = all_files(frozen_dir(world))
    assert sorted(files) == ["freeze.json", "policy.json", "prompts/baseline/pilot-book.txt",
                             "prompts/baseline/pilot-demo.txt", "prompts/skill/pilot-book.txt",
                             "prompts/skill/pilot-demo.txt", "reference-set.json", "reference/pilot-book.json",
                             "reference/pilot-demo.json"]
    for rel, data in files.items():
        text = data.decode("utf-8")
        assert not re.search(r"/Users/|/home/|/private/|(?<![A-Za-z0-9])[A-Za-z]:[\\/]", text), rel
        assert str(tmp_path) not in text, rel
        if rel.endswith(".json"):
            assert data == er.canonical_json(json.loads(data)), rel
        else:
            assert text.endswith("\n") and not text.endswith("\n\n") and "\r" not in text
    freeze_value = json.loads(files["freeze.json"])
    revision = "sha256:" + er.sha256_bytes(files["reference-set.json"])
    assert freeze_value["referenceRevision"] == revision and freeze_value["frozenAt"] == FROZEN_AT
    assert freeze_value["files"] == {rel: er.sha256_bytes(data) for rel, data in files.items() if rel != "freeze.json"}
    assert freeze_value["supersedes"] is None and freeze_value["developmentAdjudication"] is None
    assert set(freeze_value["tooling"]) == set(wd.TOOLING_FILES)
    assert freeze_value["tasksManifest"]["sha256"] == er.sha256_bytes((world.root / "evals/workflow/tasks.json").read_bytes())
    assert [task["id"] for task in freeze_value["tasksManifest"]["heldOut"]["tasks"]] == ["pilot-demo", "pilot-book"]
    assert "dev-demo" not in files["freeze.json"].decode()
    assert sorted(freeze_value["decisionFiles"]) == ["evals/workflow/decisions/pilot-book.md",
                                                     "evals/workflow/decisions/pilot-demo.md",
                                                     "evals/workflow/decisions/run-policy.md"]
    assert freeze_value["repositories"]["sparse"]["demo"] == ["lib", "/train.py", "/configs/a.py", "/README.md"]
    # tasks.json is rewritten byte-predictably.
    manifest = json.loads(tasks_before)
    for task in manifest["tasks"]:
        if task["split"] == "heldout":
            task["referenceStatus"] = "frozen"
    manifest["pilotFreeze"] = {"campaign": "pilot-99", "freeze": "pilot/pilot-99/freeze.json",
                               "referenceRevision": revision}
    assert (world.root / "evals/workflow/tasks.json").read_bytes() == (json.dumps(manifest, indent=2) + "\n").encode()
    assert er.check_task_manifest(manifest) == []
    # The frozen reference: locators and the owner's words, no third-party source text.
    reference = json.loads(files["reference/pilot-demo.json"])
    assert reference["format"] == "mlview-frozen-reference/1" and reference["campaign"] == "pilot-99"
    assert reference["essentialFactIds"] == ["demo-f01", "demo-f03"]
    assert reference["counts"] == {"facts": 3, "essential": 2, "runsMustState": 0, "nonDefects": 1, "defects": 0}
    assert reference["facts"][0]["anchors"] == [{"id": "demo-a01", "file": "train.py", "line": 10, "endLine": 11}]
    assert reference["reviews"] == [{"role": "primary", "path": "evals/workflow/decisions/pilot-demo.md",
                                     "sha256": er.sha256_file(world.root / "evals/workflow/decisions/pilot-demo.md"),
                                     "reviewer": REVIEWER, "date": DATE, "transcribedBy": None}]
    assert reference["sourceFiles"] == {rel: {"sha256": er.sha256_bytes(DEMO_FILES[rel]),
                                              "blob": er.git_blob_oid(DEMO_FILES[rel])}
                                        for rel in ("configs/a.py", "lib/model.py", "train.py")}
    assert "value_10 = 10" not in files["reference/pilot-demo.json"].decode()
    book = json.loads(files["reference/pilot-book.json"])
    assert book["facts"][0]["anchors"] == [{"id": "book-a01", "file": "book.ipynb", "cell": 1, "line": 1, "endLine": 2}]
    assert book["knownUnresolved"][0]["runsMustState"] is True
    policy = json.loads(files["policy.json"])
    assert policy["prompts"]["artifactPath"] == "pilot.mlview.json" and policy["targets"] == TARGETS
    assert policy["prompts"]["skillTemplateSha256"] == er.sha256_bytes(wd.SKILL_PROMPT_PROPOSAL.encode())
    assert policy["budget"] == {"activeMinutes": 20, "repairRounds": 2, "infrastructureRetries": 0}
    assert files["prompts/skill/pilot-demo.txt"].decode() == (
        "Explain the synthetic training loop and its defaults.\n\nSelected scenario:\n"
        "Description: Inspect train.py with its synthetic defaults and no overrides.\nEntrypoints: train.py\n"
        "Arguments: none\n\n" + wd.SKILL_PROMPT_PROPOSAL.split("\n")[-1].replace("{artifact_path}", "pilot.mlview.json")
        + "\n")
    assert "Arguments: source-order-only\n" in files["prompts/baseline/pilot-book.txt"].decode()
    # Exclusive: the same campaign again is refused, and nothing changes.
    snapshot = all_files(world.root)
    code, out = run(world, "freeze", "--campaign", "pilot-99", "--write", "--frozen-at", FROZEN_AT)
    assert code == 1 and "Cannot freeze pilot-99 (nothing written):" in out
    assert "  - evals/workflow/pilot/pilot-99 already exists. Next: choose a new campaign name; frozen campaigns are " \
           "never overwritten\n" in out
    assert all_files(world.root) == snapshot


def test_freeze_is_deterministic(tmp_path: Path, verified) -> None:
    outputs = []
    for name in ("one", "two"):
        world = make_world(tmp_path / name)
        complete_world(world)
        code, out = run(world, "freeze", "--campaign", "pilot-99", "--write", "--frozen-at", FROZEN_AT)
        assert code == 0, out
        outputs.append((all_files(frozen_dir(world)), (world.root / "evals/workflow/tasks.json").read_bytes()))
    assert outputs[0] == outputs[1]


def refused(world: wd.World, *extra: str) -> str:
    snapshot = all_files(world.root)
    code, out = run(world, "freeze", "--campaign", "pilot-99", "--write", "--frozen-at", FROZEN_AT, *extra)
    assert code == 1, out
    assert out.startswith("Cannot freeze pilot-99 (nothing written):")
    assert all_files(world.root) == snapshot
    return out


def test_freeze_refuses_pending_decisions(tmp_path: Path, verified) -> None:
    world = make_world(tmp_path)
    complete_world(world)
    write(world, "pilot-book.md", accept_all(world, "pilot-book", runs="yes"))
    out = refused(world)
    assert "  - evals/workflow/decisions/pilot-book.md: 0 error(s), 1 to do. Next: python tools/workflow_eval.py " \
           "check pilot-book" in out
    write(world, "pilot-book.md", complete(accept_all(world, "pilot-book", runs="yes")))
    write(world, "run-policy.md", wd.policy_template(world))
    assert "  - evals/workflow/decisions/run-policy.md: 0 error(s), 21 to do. Next: python tools/workflow_eval.py " \
           "check run-policy" in refused(world)


def test_freeze_refuses_blob_mismatch_and_failed_verification(tmp_path: Path, verified, monkeypatch) -> None:
    world = make_world(tmp_path)
    complete_world(world)
    (world.corpus / "demo" / "lib/model.py").write_bytes(DEMO_FILES["lib/model.py"] + b"extra = 1\n")
    out = refused(world)
    assert "lib/model.py in demo differs from the pinned blob" in out
    (world.corpus / "demo" / "lib/model.py").write_bytes(DEMO_FILES["lib/model.py"])
    monkeypatch.setattr(fetch_workflow_repos, "verify_repo",
                        lambda repo, root: {"ok": repo["name"] != "book", "clean": False, "missing": ["x"]})
    assert "  - book: the checkout failed verification (clean: False; missing: ['x']). Next: python " \
           "tools/fetch_workflow_repos.py --verify" in refused(world)
    monkeypatch.setattr(fetch_workflow_repos, "verify_repo",
                        lambda repo, root: {"ok": repo["name"] != "book", "problems": [
                            "book: sparse patterns differ from the manifest (missing: /x); re-run with --update-sparse"]})
    assert "  - book: the checkout failed verification (book: sparse patterns differ from the manifest (missing: /x); " \
           "re-run with --update-sparse). Next: python tools/fetch_workflow_repos.py --update-sparse --repo book, " \
           "then python tools/fetch_workflow_repos.py --verify" in refused(world)
    monkeypatch.delattr(fetch_workflow_repos, "verify_repo")
    assert "corpus verification is not available in this build (tools/fetch_workflow_repos.py has no verify_repo)" \
        in refused(world)


def test_freeze_refuses_absent_corpus(tmp_path: Path, verified) -> None:
    world = make_world(tmp_path)
    complete_world(world)
    snapshot = all_files(world.root)
    code, out = run(world, "freeze", "--campaign", "pilot-99", "--write", corpus=None)
    assert code == 1 and "  - the corpus is absent; the freeze needs every pinned repository. Next: set " \
                         "MLVIEW_PUBLIC_CORPUS_DIR or run python tools/fetch_workflow_repos.py" in out
    assert out.count("corpus is absent") == 1 and all_files(world.root) == snapshot


def test_freeze_refuses_placeholder_scenario(tmp_path: Path, verified) -> None:
    world = make_world(tmp_path, placeholder=True)
    complete_world(world)
    assert "  - evals/workflow/decisions/pilot-book.md: 1 error(s), 0 to do." in refused(world)


def test_freeze_refuses_reference_leak(tmp_path: Path, verified) -> None:
    world = make_world(tmp_path)
    complete_world(world)
    leaking = in_section(accept_all(world, "pilot-demo"), "Scenario", "Decision: accept", [
        "Decision: replace", "Description: The synthetic loop accumulates forty micro-steps before each update.",
        "Entrypoints: train.py", "Arguments: none", "Reason: synthetic"])
    write(world, "pilot-demo.md", complete(leaking))
    out = refused(world)
    assert "  - prompts/skill/pilot-demo.txt contains the reference text of demo-f01 (reference leakage); change the " \
           "scenario or the prompt template. Next: edit the scenario in the task's decisions file or the prompt " \
           "template" in out
    assert "prompts/baseline/pilot-demo.txt contains the reference text of demo-f01" in out


def test_freeze_refuses_absolute_path_in_a_prompt(tmp_path: Path, verified) -> None:
    world = make_world(tmp_path, prompt="Explain the loop in /Users/someone/demo/train.py.")
    complete_world(world)
    assert "  - prompts/skill/pilot-demo.txt contains an absolute machine path (/Users/)." in refused(world)


def test_freeze_refuses_unfetched_candidate_anchor(tmp_path: Path, verified) -> None:
    world = make_world(tmp_path, uncovered_anchor=True)
    complete_world(world)
    assert "  - pilot-demo: configs/other.py is not fetched by repositories.json (demo sparse list). Next: ask the " \
           "maintainer to add it to the sparse list, then python tools/fetch_workflow_repos.py --update-sparse" in \
        refused(world)


def test_freeze_refuses_non_canonical_tasks_json_and_bad_arguments(tmp_path: Path, verified) -> None:
    world = make_world(tmp_path)
    complete_world(world)
    path = world.root / "evals/workflow/tasks.json"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert "tasks.json is not canonical JSON" in refused(world)
    assert run(world, "freeze", "--campaign", "Pilot 1")[0] == 2
    assert run(world, "freeze", "--campaign", "pilot-99", "--frozen-at", "2026-01-03T10:00:00+01:00")[0] == 2


def test_freeze_notes_the_development_adjudication_gate(tmp_path: Path, verified) -> None:
    world = make_world(tmp_path)
    complete_world(world, adjudication="required")
    code, out = run(world, "freeze", "--campaign", "pilot-99")
    assert code == 0
    assert "  note: the run policy requires the development adjudication before Stage 1; run-prepare will refuse " \
           "Stage 1 runs until evals/workflow/decisions/development-adjudication.md is complete (it is not complete " \
           "now)." in out


def test_supersede_rules(tmp_path: Path, verified) -> None:
    world = make_world(tmp_path)
    complete_world(world)
    assert run(world, "freeze", "--campaign", "pilot-98", "--write", "--frozen-at", FROZEN_AT)[0] == 0
    out = refused(world)
    assert "  - evals/workflow/tasks.json is not in the pre-freeze state: campaign pilot-98 is frozen. Next: a new " \
           'campaign may supersede pilot-98 only with --supersede-reason "<why>"' in out
    synthetic_candidate(world, "pilot-98")
    out = refused(world, "--supersede-reason", "synthetic reason")
    assert "pilot-98 was captured (it has candidate.json), so it can be superseded only after an owner-authored " \
           "invalidation.md (it does not exist)" in out
    (frozen_dir(world, "pilot-98") / "invalidation.md").write_text(
        f"# Invalidation: pilot-98\nReviewer: {REVIEWER}\nDate: {DATE}\nScope: campaign\nReason: synthetic\n",
        encoding="utf-8")
    code, out = run(world, "freeze", "--campaign", "pilot-99", "--write", "--frozen-at", FROZEN_AT,
                    "--supersede-reason", "synthetic reason")
    assert code == 0, out
    assert "Updated evals/workflow/tasks.json: pilotFreeze pilot-98 -> pilot-99 (supersedes pilot-98: synthetic " \
           "reason)" in out
    assert json.loads((frozen_dir(world) / "freeze.json").read_text(encoding="utf-8"))["supersedes"] == {
        "campaign": "pilot-98", "reason": "synthetic reason"}
    assert json.loads((world.root / "evals/workflow/tasks.json").read_text(encoding="utf-8"))["pilotFreeze"]["campaign"] == "pilot-99"
    code, out = run(world, "check-frozen")
    assert code == 0, out
    assert "check-frozen: pilot-98 (superseded): hashes intact." in out


def test_supersede_without_candidate_needs_only_a_reason(tmp_path: Path, verified) -> None:
    world = make_world(tmp_path)
    complete_world(world)
    assert run(world, "freeze", "--campaign", "pilot-98", "--write", "--frozen-at", FROZEN_AT)[0] == 0
    code, out = run(world, "freeze", "--campaign", "pilot-99", "--frozen-at", FROZEN_AT, "--supersede-reason", "why")
    assert code == 0 and "Would update evals/workflow/tasks.json: pilotFreeze pilot-98 -> pilot-99" in out
    assert run(world, "freeze", "--campaign", "pilot-98", "--supersede-reason", "why")[0] == 1
    fresh = make_world(tmp_path / "fresh")
    complete_world(fresh)
    assert "  - --supersede-reason was given but no campaign is frozen. Next: drop --supersede-reason" in \
        refused(fresh, "--supersede-reason", "why")


# --------------------------------------------------------------------------------------------
# check-frozen


def frozen_world(tmp_path: Path) -> wd.World:
    world = make_world(tmp_path)
    complete_world(world)
    code, out = run(world, "freeze", "--campaign", "pilot-99", "--write", "--frozen-at", FROZEN_AT)
    assert code == 0, out
    return world


HISTORY_NOTE = ("check-frozen: pilot-99: not verified without the full Git history (the repository root is not a Git "
                "work tree): freeze.json against its first commit, and whether a committed campaign, candidate.json "
                "or stage summary was removed or changed.")


def test_check_frozen_passes_with_and_without_the_corpus(tmp_path: Path, verified) -> None:
    world = frozen_world(tmp_path)
    code, out = run(world, "check-frozen")
    assert (code, out.splitlines()) == (0, [
        "check-frozen: pilot-99 re-derived byte for byte (2 references, reference-set.json, policy.json, 4 prompts, "
        "freeze.json); held-out tasks.json fields unchanged.", HISTORY_NOTE])
    code, out = run(world, "check-frozen", corpus=None)
    assert code == 0 and out.splitlines()[-2:] == ["source hashes not re-read: corpus absent", HISTORY_NOTE]


def test_check_frozen_catches_an_edited_decision_file(tmp_path: Path, verified) -> None:
    world = frozen_world(tmp_path)
    path = world.root / wd.DECISIONS_REL / "pilot-demo.md"
    path.write_text(path.read_text(encoding="utf-8").replace("Fact demo-f02\n", "Fact demo-f02\n", 1).replace(
        "## Fact demo-f02\n> Claim: The synthetic model width comes from lib/model.py constants.\n"
        "> Basis: observed. Essential: no. Anchors: lib/model.py:3\nDecision: accept",
        "## Fact demo-f02\n> Claim: The synthetic model width comes from lib/model.py constants.\n"
        "> Basis: observed. Essential: no. Anchors: lib/model.py:3\nDecision: accept\nEssential: yes\n"
        "Reason: changed after the freeze (synthetic)"), encoding="utf-8")
    code, out = run(world, "check-frozen", corpus=None)
    assert code == 1
    assert "check-frozen: evals/workflow/pilot/pilot-99/reference/pilot-demo.json differs from the re-derivation (an " \
           "edited frozen file, decision file, ledger or manifest)" in out
    assert "freeze.json differs from the re-derivation" in out


def test_check_frozen_catches_an_edited_frozen_file(tmp_path: Path, verified) -> None:
    world = frozen_world(tmp_path)
    reference = frozen_dir(world) / "reference/pilot-demo.json"
    value = json.loads(reference.read_text(encoding="utf-8"))
    value["essentialFactIds"] = ["demo-f01"]
    reference.write_bytes(er.canonical_json(value))
    code, out = run(world, "check-frozen")
    assert code == 1 and "check-frozen: evals/workflow/pilot/pilot-99/reference/pilot-demo.json differs from its hash " \
                         "in freeze.json (frozen files are immutable)" in out
    # Consistently updated hashes do not help: the files are re-derived from the decisions.
    freeze_path = frozen_dir(world) / "freeze.json"
    freeze_value = json.loads(freeze_path.read_text(encoding="utf-8"))
    freeze_value["files"]["reference/pilot-demo.json"] = er.sha256_file(reference)
    freeze_path.write_bytes(er.canonical_json(freeze_value))
    code, out = run(world, "check-frozen")
    assert code == 1 and "reference/pilot-demo.json differs from the re-derivation" in out


def test_check_frozen_catches_held_out_drift_but_allows_development_edits(tmp_path: Path, verified) -> None:
    world = frozen_world(tmp_path)
    path = world.root / "evals/workflow/tasks.json"
    original = path.read_bytes()
    manifest = json.loads(original)
    manifest["tasks"][0]["prompt"] = "An edited synthetic development prompt."
    path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode())
    assert run(world, "check-frozen")[0] == 0
    manifest["tasks"][1]["prompt"] = "A drifted held-out prompt."
    path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode())
    code, out = run(world, "check-frozen")
    assert code == 1 and "check-frozen: evals/workflow/tasks.json held-out fields changed after the freeze of pilot-99" in out
    manifest = json.loads(original)
    manifest["tasks"][1]["referenceStatus"] = "needs-human-review"
    path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode())
    code, out = run(world, "check-frozen")
    assert code == 1 and "pilot-demo: a held-out task must be frozen after the freeze of pilot-99" in out


def test_check_frozen_requires_a_pointer_for_committed_campaigns(tmp_path: Path, verified) -> None:
    world = frozen_world(tmp_path)
    path = world.root / "evals/workflow/tasks.json"
    manifest = json.loads(path.read_bytes())
    manifest.pop("pilotFreeze")
    for task in manifest["tasks"]:
        task["referenceStatus"] = "needs-human-review"
    path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode())
    code, out = run(world, "check-frozen")
    assert code == 1 and "freeze.json exists but evals/workflow/tasks.json has no pilotFreeze" in out


SYNTHETIC_LABEL = "computed against the predefined targets; not an approval"


def synthetic_candidate(world: wd.World, campaign: str = "pilot-99") -> bytes:
    """A minimal version 2 pilot-candidate record naming the committed freeze.json (synthetic)."""
    directory = frozen_dir(world, campaign)
    freeze_raw = (directory / "freeze.json").read_bytes()
    record = {"version": 2, "kind": "pilot-candidate", "campaign": campaign, "pilotApproved": False,
              "components": [{"path": f"evals/workflow/pilot/{campaign}/freeze.json", "sha256": er.sha256_bytes(freeze_raw),
                              "bytes": len(freeze_raw)}],
              "note": "synthetic candidate for tests"}
    raw = er.canonical_json(record)
    (directory / "candidate.json").write_bytes(raw)
    return raw


def synthetic_summary(world: wd.World, value: str, *, campaign: str = "pilot-99", number: str = "1") -> None:
    """Stage summary files in the recorded format for the synthetic candidate (synthetic computed values)."""
    directory = frozen_dir(world, campaign)
    candidate_sha = er.sha256_file(directory / "candidate.json")
    freeze_raw = (directory / "freeze.json").read_bytes()
    summary = {"format": "mlview-pilot-summary/1", "campaign": campaign, "stage": "1" if number == "1" else "all",
               "generatedAt": "2026-10-09T10:00:00Z", "candidateSha256": candidate_sha,
               "referenceRevision": json.loads(freeze_raw)["referenceRevision"],
               "inputs": {"candidate": candidate_sha, "freeze": er.sha256_bytes(freeze_raw)},
               "decision": {"value": value, "label": SYNTHETIC_LABEL}, "note": "synthetic summary for tests",
               "pilotApproved": False}
    title = "Stage 1 summary" if number == "1" else "all-stage summary"
    (directory / f"stage{number}-summary.json").write_bytes(er.canonical_json(summary))
    (directory / f"stage{number}-summary.md").write_bytes(
        f"# MLView pilot {campaign} \u2014 {title} (2026-10-09)\n**Decision: {value.upper()}** \u2014 {SYNTHETIC_LABEL}.\n"
        "\nSynthetic summary for tests.\n".encode("utf-8"))


def rewrite_frozen_chain(world: wd.World) -> None:
    """Drop an essential fact from a frozen reference and update every hash consistently."""
    directory = frozen_dir(world)
    ref_path = directory / "reference/pilot-demo.json"
    ref = json.loads(ref_path.read_text(encoding="utf-8"))
    ref["essentialFactIds"] = ref["essentialFactIds"][:1]
    ref_path.write_bytes(er.canonical_json(ref))
    set_path = directory / "reference-set.json"
    reference_set = json.loads(set_path.read_text(encoding="utf-8"))
    for entry in reference_set["tasks"]:
        if entry["task"] == "pilot-demo":
            entry["sha256"] = er.sha256_file(ref_path)
    set_path.write_bytes(er.canonical_json(reference_set))
    freeze_path = directory / "freeze.json"
    freeze_value = json.loads(freeze_path.read_text(encoding="utf-8"))
    freeze_value["files"]["reference/pilot-demo.json"] = er.sha256_file(ref_path)
    freeze_value["files"]["reference-set.json"] = er.sha256_file(set_path)
    freeze_value["referenceRevision"] = "sha256:" + er.sha256_file(set_path)
    freeze_path.write_bytes(er.canonical_json(freeze_value))
    tasks_path = world.root / "evals/workflow/tasks.json"
    tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks["pilotFreeze"]["referenceRevision"] = freeze_value["referenceRevision"]
    tasks_path.write_bytes((json.dumps(tasks, indent=2) + "\n").encode())


def test_check_frozen_is_integrity_only_once_a_final_summary_is_recorded(tmp_path: Path, verified) -> None:
    world = frozen_world(tmp_path)
    synthetic_candidate(world)
    synthetic_summary(world, "stop")
    decisions = world.root / wd.DECISIONS_REL / "run-policy.md"
    decisions.write_text(decisions.read_text(encoding="utf-8").replace("Active minutes: 20", "Active minutes: 30"), encoding="utf-8")
    code, out = run(world, "check-frozen")
    assert code == 0 and "check-frozen: pilot-99 (final summary recorded): hashes intact." in out, out
    # Hash-only still binds freeze.json to the candidate and the ledgers to their frozen bytes.
    rewrite_frozen_chain(world)
    code, out = run(world, "check-frozen")
    assert code == 1 and "pilot-99/freeze.json differs from the freeze.json that candidate.json identifies" in out, out


def test_check_frozen_keeps_rederiving_beside_a_fake_or_empty_summary(tmp_path: Path, verified) -> None:
    world = frozen_world(tmp_path)
    directory = frozen_dir(world)
    (directory / "stage2-summary.json").write_bytes(b"")
    rewrite_frozen_chain(world)
    code, out = run(world, "check-frozen")
    assert code == 1 and "stage2-summary.json exist(s) without candidate.json" in out, out
    assert "reference/pilot-demo.json differs from the re-derivation" in out
    (directory / "stage2-summary.json").unlink()
    synthetic_candidate(world)
    (directory / "stage1-summary.json").write_text('{"decision": {"value": "stop"}}', encoding="utf-8")
    (directory / "stage1-summary.md").write_bytes(b"# not a summary\n")
    code, out = run(world, "check-frozen")
    assert code == 1 and "stage1-summary.json is not a recorded summary of this candidate (format is not" in out, out
    assert "reference/pilot-demo.json differs from the re-derivation" in out
    (directory / "stage1-summary.md").unlink()
    (directory / "stage1-summary.json").unlink()
    (directory / "stage1-summary.txt").write_text("synthetic", encoding="utf-8")
    code, out = run(world, "check-frozen")
    assert code == 1 and "stage1-summary.txt is not a file summarize --record writes" in out


def test_check_frozen_after_a_final_summary_catches_an_edited_ledger(tmp_path: Path, verified) -> None:
    world = frozen_world(tmp_path)
    synthetic_candidate(world)
    synthetic_summary(world, "go")
    synthetic_summary(world, "targets-met", number="2")
    code, out = run(world, "check-frozen")
    assert code == 0 and "(final summary recorded): hashes intact." in out, out
    ledger = world.root / "evals/workflow/reference-candidates/pilot-demo.json"
    ledger.write_bytes(ledger.read_bytes() + b"\n")
    code, out = run(world, "check-frozen")
    assert code == 1 and "evals/workflow/reference-candidates/pilot-demo.json differs from the ledger frozen in " \
                         "pilot-99 (candidate ledgers are immutable)" in out, out


def test_check_frozen_verifies_the_copied_freeze_fields(tmp_path: Path, verified) -> None:
    world = frozen_world(tmp_path)
    freeze_path = frozen_dir(world) / "freeze.json"
    original = freeze_path.read_bytes()
    value = json.loads(original)
    value["supersedes"] = {"campaign": "pilot-00", "reason": "invented (synthetic)"}
    value["developmentAdjudication"] = {"path": "evals/workflow/decisions/elsewhere.md", "sha256": "f" * 64,
                                        "complete": True}
    value["tasksManifest"]["sha256"] = "0" * 64
    freeze_path.write_bytes(er.canonical_json(value))
    code, out = run(world, "check-frozen")
    assert code == 1
    assert "pilot-99/freeze.json supersedes 'pilot-00', which is not another frozen campaign" in out
    assert "developmentAdjudication must be null or {path: evals/workflow/decisions/development-adjudication.md" in out
    # Without Git history the tasks.json hash cannot be traced, and the check says so.
    assert "check-frozen: pilot-99: not verified: tasksManifest.sha256" in out


def test_check_frozen_names_a_changed_decision_file(tmp_path: Path, verified) -> None:
    world = frozen_world(tmp_path)
    path = world.root / wd.DECISIONS_REL / "run-policy.md"
    path.write_text(path.read_text(encoding="utf-8").replace("Active minutes: 20", "Active minutes: 30"), encoding="utf-8")
    code, out = run(world, "check-frozen")
    assert code == 1 and "check-frozen: evals/workflow/decisions/run-policy.md changed after the freeze of pilot-99; a " \
                         "changed decision needs a new campaign (evals/workflow/pilot/README.md)" in out, out
    fresh = wd.World(world.root, world.corpus)
    checks = wd.check_path(fresh, path)
    assert "frozen in pilot-99" not in checks[0].summary[0]
    assert any("this file was frozen in pilot-99" in p.message for p in checks[0].problems)
    primary = world.root / wd.DECISIONS_REL / "pilot-demo.md"
    assert wd.check_path(fresh, primary)[0].summary[0].endswith("; frozen in pilot-99.")


def git_world(world: wd.World) -> None:
    git(world.root, "init", "--quiet")
    git(world.root, "add", "-A")
    git(world.root, "commit", "--quiet", "-m", "synthetic freeze")


def test_a_deleted_candidate_still_needs_an_invalidation_to_supersede(tmp_path: Path, verified) -> None:
    world = make_world(tmp_path)
    complete_world(world)
    assert run(world, "freeze", "--campaign", "pilot-98", "--write", "--frozen-at", FROZEN_AT)[0] == 0
    git_world(world)
    old = frozen_dir(world, "pilot-98")
    synthetic_candidate(world, "pilot-98")
    git(world.root, "add", "-A")
    git(world.root, "commit", "--quiet", "-m", "synthetic capture")
    code, out = run(world, "check-frozen")
    assert code == 0, out
    git(world.root, "rm", "--quiet", str(old / "candidate.json"))
    git(world.root, "commit", "--quiet", "-m", "synthetic deletion")
    code, out = run(world, "check-frozen")
    assert code == 1 and "evals/workflow/pilot/pilot-98/candidate.json was committed in" in out and \
        "is missing now (a campaign has one candidate; it is never removed or replaced)" in out, out
    out = refused(world, "--supersede-reason", "re-roll (synthetic)")
    assert "pilot-98 was captured (candidate.json was committed in" in out
    assert "; deleting it does not undo the capture), so it can be superseded only after an owner-authored " \
           "invalidation.md (it does not exist)" in out


def test_git_history_binds_the_copied_freeze_fields(tmp_path: Path, verified) -> None:
    world = frozen_world(tmp_path)
    freeze_path = frozen_dir(world) / "freeze.json"
    value = json.loads(freeze_path.read_text(encoding="utf-8"))
    value["tasksManifest"]["sha256"] = "0" * 64
    freeze_path.write_bytes(er.canonical_json(value))
    git_world(world)
    code, out = run(world, "check-frozen")
    assert code == 1 and "pilot-99/freeze.json tasksManifest.sha256 differs from the evals/workflow/tasks.json " \
                         "committed with it in" in out, out


def test_git_history_binds_the_committed_freeze(tmp_path: Path, verified) -> None:
    world = frozen_world(tmp_path)
    git_world(world)
    code, out = run(world, "check-frozen")
    assert code == 0 and "not verified" not in out, out
    tasks_path = world.root / "evals/workflow/tasks.json"
    manifest = json.loads(tasks_path.read_text(encoding="utf-8"))
    manifest["tasks"][0]["prompt"] = "An edited synthetic development prompt."
    tasks_path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode())
    git(world.root, "commit", "--quiet", "-am", "synthetic development edit")
    code, out = run(world, "check-frozen")
    assert code == 0 and "not verified" not in out, out
    synthetic_candidate(world)
    synthetic_summary(world, "stop")
    git(world.root, "add", "-A")
    git(world.root, "commit", "--quiet", "-m", "synthetic summary")
    assert run(world, "check-frozen")[0] == 0
    # A consistent rewrite of freeze.json, candidate.json and the summary still differs from the commit.
    rewrite_frozen_chain(world)
    synthetic_candidate(world)
    for name in ("stage1-summary.json", "stage1-summary.md"):
        (frozen_dir(world) / name).unlink()
    synthetic_summary(world, "stop")
    code, out = run(world, "check-frozen")
    assert code == 1 and "evals/workflow/pilot/pilot-99/freeze.json differs from the version committed in" in out, out
    value = json.loads((frozen_dir(world) / "freeze.json").read_text(encoding="utf-8"))
    assert value["tasksManifest"]["sha256"]


def test_a_tasks_json_committed_apart_from_the_freeze_is_noted(tmp_path: Path, verified) -> None:
    world = frozen_world(tmp_path)
    tasks_path = world.root / "evals/workflow/tasks.json"
    frozen = tasks_path.read_bytes()
    manifest = json.loads(frozen)
    manifest.pop("pilotFreeze")
    tasks_path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode())
    git_world(world)  # freeze.json is committed with a tasks.json that does not name the campaign
    manifest = json.loads(frozen)
    manifest["tasks"][0]["prompt"] = "An edited synthetic development prompt."
    tasks_path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode())
    git(world.root, "commit", "--quiet", "-am", "synthetic separate manifest")
    code, out = run(world, "check-frozen")
    assert code == 0 and "check-frozen: pilot-99: not verified: tasksManifest.sha256 (evals/workflow/tasks.json was " \
                         "committed separately from freeze.json)" in out, out


def commit_all(world: wd.World, message: str) -> None:
    git(world.root, "add", "-A")
    git(world.root, "commit", "--quiet", "-m", message)


@pytest.mark.parametrize("number, first, then", [("1", "stop", "go"), ("2", "targets-missed", "targets-met")])
def test_a_committed_summary_cannot_be_removed_or_replaced(tmp_path: Path, verified, number: str, first: str,
                                                           then: str) -> None:
    """A recorded summary is final: deleting a committed one, or recording another after it, fails (INTEGRITY2-1)."""
    world = frozen_world(tmp_path)
    git_world(world)
    synthetic_candidate(world)
    if number == "2":
        synthetic_summary(world, "go")
    synthetic_summary(world, first, number=number)
    commit_all(world, "synthetic capture and summary")
    code, out = run(world, "check-frozen")
    assert code == 0 and "(final summary recorded): hashes intact." in out, out
    names = [f"stage{number}-summary.json", f"stage{number}-summary.md"]
    git(world.root, "rm", "--quiet", *[str(frozen_dir(world) / name) for name in names])
    git(world.root, "commit", "--quiet", "-m", "synthetic removal of the summary")
    code, out = run(world, "check-frozen")
    for name in names:
        assert code == 1 and f"check-frozen: evals/workflow/pilot/pilot-99/{name} was committed in " in out, out
        assert f"pilot-99/{name} was committed in" in out and "is missing now (a recorded summary is final)" in out
    synthetic_summary(world, then, number=number)
    commit_all(world, "synthetic replacement summary")
    code, out = run(world, "check-frozen")
    assert code == 1
    for name in names:
        assert f"evals/workflow/pilot/pilot-99/{name} differs from the version first committed in" in out, out
        assert f"evals/workflow/pilot/pilot-99/{name} was committed with 2 different contents (" in out, out


def shallow_clone(world: wd.World, target: Path) -> wd.World:
    subprocess.run(["git", "clone", "--quiet", "--depth", "1", world.root.resolve().as_uri(), str(target)], check=True,
                   capture_output=True, env=git_env())
    assert git(target, "rev-parse", "--is-shallow-repository").strip() == "true"
    return wd.World(target, world.corpus)


def test_a_shallow_clone_says_which_history_checks_did_not_run(tmp_path: Path, verified) -> None:
    """Without the full history the lost-candidate, lost-summary and first-commit checks are named (INTEGRITY2-4)."""
    world = frozen_world(tmp_path / "a")
    git_world(world)
    synthetic_candidate(world)
    commit_all(world, "synthetic capture")
    git(world.root, "rm", "--quiet", str(frozen_dir(world) / "candidate.json"))
    git(world.root, "commit", "--quiet", "-m", "synthetic deletion")
    code, out = run(world, "check-frozen")
    assert code == 1 and "is missing now (a campaign has one candidate; it is never removed or replaced)" in out, out
    assert "not verified" not in out
    shallow = shallow_clone(world, tmp_path / "shallow")
    code, out = run(shallow, "check-frozen")
    assert code == 0, out
    assert "check-frozen: pilot-99: not verified without the full Git history (this is a shallow clone (git fetch " \
           "--unshallow gives the full history)): freeze.json against its first commit, and whether a committed " \
           "campaign, candidate.json or stage summary was removed or changed." in out, out


def test_a_superseded_captured_campaign_is_bound_to_its_candidate_without_a_summary(tmp_path: Path, verified) -> None:
    """The hash-only check binds freeze.json to candidate.json even before any summary (SPECDOCS2-2)."""
    world = make_world(tmp_path)
    complete_world(world)
    assert run(world, "freeze", "--campaign", "pilot-98", "--write", "--frozen-at", FROZEN_AT)[0] == 0
    synthetic_candidate(world, "pilot-98")
    (frozen_dir(world, "pilot-98") / "invalidation.md").write_text(
        f"# Invalidation: pilot-98\nReviewer: {REVIEWER}\nDate: {DATE}\nScope: campaign\nReason: synthetic\n",
        encoding="utf-8")
    code, out = run(world, "freeze", "--campaign", "pilot-99", "--write", "--frozen-at", FROZEN_AT,
                    "--supersede-reason", "synthetic reason")
    assert code == 0, out
    assert run(world, "check-frozen")[0] == 0
    directory = frozen_dir(world, "pilot-98")
    ref_path = directory / "reference/pilot-demo.json"
    ref = json.loads(ref_path.read_text(encoding="utf-8"))
    ref["essentialFactIds"] = ref["essentialFactIds"][:1]
    ref_path.write_bytes(er.canonical_json(ref))
    set_path = directory / "reference-set.json"
    reference_set = json.loads(set_path.read_text(encoding="utf-8"))
    for entry in reference_set["tasks"]:
        if entry["task"] == "pilot-demo":
            entry["sha256"] = er.sha256_file(ref_path)
    set_path.write_bytes(er.canonical_json(reference_set))
    freeze_path = directory / "freeze.json"
    freeze_value = json.loads(freeze_path.read_text(encoding="utf-8"))
    freeze_value["files"]["reference/pilot-demo.json"] = er.sha256_file(ref_path)
    freeze_value["files"]["reference-set.json"] = er.sha256_file(set_path)
    freeze_value["referenceRevision"] = "sha256:" + er.sha256_file(set_path)
    freeze_path.write_bytes(er.canonical_json(freeze_value))
    code, out = run(world, "check-frozen")
    assert code == 1 and "check-frozen: evals/workflow/pilot/pilot-98/freeze.json differs from the freeze.json that " \
                         "candidate.json identifies (frozen files are immutable)" in out, out
    assert "pilot-98 (superseded): hashes intact." not in out


def test_a_second_review_added_after_the_freeze_is_named(tmp_path: Path, verified) -> None:
    """check notes a decision file the freeze did not include, and check-frozen names it (OWNERUX2-5)."""
    world = frozen_world(tmp_path)
    second = fill_header(wd.task_template(world, "pilot-demo", second=True), SECOND)
    second = decide(second, "Fact demo-f01", "accept")
    path = write(world, "pilot-demo.second.md", complete(second))
    code, out = run(world, "check", "pilot-demo")
    assert "pilot-demo: 0 error(s), 0 to do; frozen in pilot-99." in out, out
    assert "evals/workflow/decisions/pilot-demo.second.md:1: NOTE  header: this file was added after the freeze of " \
           "pilot-99, which did not include it; a changed decision needs a new campaign " \
           "(evals/workflow/pilot/README.md)." in out, out
    assert "pilot-demo (second review): 0 error(s), 0 to do; added after the freeze of pilot-99." in out, out
    assert "ready to freeze" not in out
    code, out = run(world, "check-frozen")
    assert code == 1 and "check-frozen: evals/workflow/decisions/pilot-demo.second.md was added after the freeze of " \
                         "pilot-99; a changed decision needs a new campaign (evals/workflow/pilot/README.md)" in out, out
    path.unlink()
    assert run(world, "check-frozen")[0] == 0


def test_check_frozen_without_a_freeze(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    assert run(world, "check-frozen") == (0, "check-frozen: not verified without the full Git history (the repository "
                                             "root is not a Git work tree): whether a committed campaign was removed.\n"
                                             "check-frozen: no frozen campaign (evals/workflow/tasks.json has no "
                                             "pilotFreeze); nothing to check.\n")
    git_world(world)
    assert run(world, "check-frozen") == (0, "check-frozen: no frozen campaign (evals/workflow/tasks.json has no "
                                             "pilotFreeze); nothing to check.\n")


def test_no_code_path_writes_owner_values() -> None:
    """Every whole-line value literal in the tool is pending: no code path spells out a decision,
    verdict or completion to write into an owner file (the dynamic template tests check the output)."""
    import ast
    tree = ast.parse((ROOT / "tools/workflow_decisions.py").read_text(encoding="utf-8"))
    literals = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    lines = [line for literal in literals for line in literal.split("\n")]
    assigned = [line for line in lines
                if re.fullmatch(r"(Decision|Review|Runs must state|Essential|Basis|Severity|Reviewer|Date|"
                                r"[a-z][a-z0-9-]*|usability\.\w+): \S+", line)]
    assert assigned and set(assigned) <= {"Decision: pending", "Review: pending"}, assigned


def test_frozen_reference_records_every_decision_kind(tmp_path: Path, verified) -> None:
    """The frozen reference format that stream B reads (specification section 1.9)."""
    world = make_world(tmp_path)
    complete_world(world)
    text = fill_header(wd.task_template(world, "pilot-demo"))
    text = decide(text, "Scenario", "replace", "Description: Inspect train.py and lib/model.py (synthetic).",
                  "Entrypoints: train.py; lib/model.py", "Arguments: none", "Reason: the model file matters (synthetic)")
    text = decide(text, "Fact demo-f01", "qualify", "Wording: Forty micro-steps per update without parallelism.",
                  "Anchors: train.py:10-11; train.py:40-41", "Reason: lines 40-41 matter (synthetic)")
    text = decide(text, "Fact demo-f02", "reject", "Reason: not needed (synthetic)")
    text = decide(text, "Fact demo-f03", "accept", "Essential: no", "Reason: not essential (synthetic)")
    text = decide(text, "Unknown demo-u01", "qualify", "Wording: The synthetic data is unknown.",
                  "Reason: shorter (synthetic)", runs="yes")
    text = decide(text, "Unknown demo-u02", "reject", "Reason: irrelevant (synthetic)")
    text = decide(text, "Non-defect demo-n01", "reject", "Reason: it is a defect (synthetic)")
    text = insert_before(text, "## Disagreements", [
        "## Added fact demo-h01", "Wording: A synthetic added fact.", "Basis: inferred", "Essential: yes",
        "Anchors: lib/model.py:7-8", "Reason: synthetic", "",
        "## Added unknown demo-hu01", "Wording: A synthetic added unknown.", "Runs must state: no", "Reason: synthetic", "",
        "## Defect demo-d01", "Wording: A synthetic defect.", "Severity: low", "Anchors: train.py:50",
        "Counter-evidence: none (synthetic)", "Reason: synthetic", ""])
    write(world, "pilot-demo.md", complete(text))
    code, out = run(world, "freeze", "--campaign", "pilot-99", "--write", "--frozen-at", FROZEN_AT)
    assert code == 0, out
    reference = json.loads((frozen_dir(world) / "reference/pilot-demo.json").read_text(encoding="utf-8"))
    assert reference["scenario"] == {"decision": "replace", "description": "Inspect train.py and lib/model.py (synthetic).",
                                     "entrypoints": ["train.py", "lib/model.py"], "arguments": [],
                                     "reason": "the model file matters (synthetic)"}
    assert reference["facts"] == [
        {"id": "demo-f01", "origin": "candidate", "decision": "qualify",
         "claim": "Forty micro-steps per update without parallelism.",
         "candidateClaim": "The synthetic loop accumulates forty micro-steps before each update.",
         "basis": "observed", "essential": True, "changed": ["anchors", "claim"],
         "anchors": [{"id": "demo-a01", "file": "train.py", "line": 10, "endLine": 11},
                     {"id": "demo-f01-h1", "file": "train.py", "line": 40, "endLine": 41}],
         "reason": "lines 40-41 matter (synthetic)"},
        {"id": "demo-f03", "origin": "candidate", "decision": "accept",
         "claim": "Synthetic evaluation probably reuses the training batch size.",
         "candidateClaim": "Synthetic evaluation probably reuses the training batch size.",
         "basis": "inferred", "essential": False, "changed": ["essential"],
         "anchors": [{"id": "demo-a03", "file": "train.py", "line": 20, "endLine": 22},
                     {"id": "demo-a04", "file": "configs/a.py", "line": 2, "endLine": 2}],
         "reason": "not essential (synthetic)"},
        {"id": "demo-h01", "origin": "added", "decision": "added", "claim": "A synthetic added fact.",
         "candidateClaim": None, "basis": "inferred", "essential": True, "changed": [],
         "anchors": [{"id": "demo-h01-a1", "file": "lib/model.py", "line": 7, "endLine": 8}], "reason": "synthetic"}]
    assert reference["rejectedFacts"] == [{"id": "demo-f02", "candidateClaim": "The synthetic model width comes from "
                                           "lib/model.py constants.", "reason": "not needed (synthetic)"}]
    assert reference["essentialFactIds"] == ["demo-f01", "demo-h01"]
    assert reference["knownUnresolved"] == [
        {"id": "demo-u01", "origin": "candidate", "decision": "qualify", "text": "The synthetic data is unknown.",
         "candidateText": "The synthetic dataset contents are not established by the source files.",
         "runsMustState": True, "reason": "shorter (synthetic)"},
        {"id": "demo-hu01", "origin": "added", "decision": "added", "text": "A synthetic added unknown.",
         "candidateText": None, "runsMustState": False, "reason": "synthetic"}]
    assert reference["rejectedUnknowns"] == [{"id": "demo-u02", "candidateText": "Runtime hardware for the synthetic run "
                                              "is unknown.", "reason": "irrelevant (synthetic)"}]
    assert reference["nonDefects"] == [] and reference["rejectedNonDefects"][0]["id"] == "demo-n01"
    assert reference["defects"] == [{"id": "demo-d01", "text": "A synthetic defect.", "severity": "low",
                                     "anchors": [{"id": "demo-d01-a1", "file": "train.py", "line": 50, "endLine": 50}],
                                     "counterEvidence": "none (synthetic)", "reason": "synthetic"}]
    assert reference["counts"] == {"facts": 3, "essential": 2, "runsMustState": 1, "nonDefects": 0, "defects": 1}
    assert sorted(reference["sourceFiles"]) == ["configs/a.py", "lib/model.py", "train.py"]
    reference_set = json.loads((frozen_dir(world) / "reference-set.json").read_text(encoding="utf-8"))
    assert reference_set["totals"] == {"tasks": 2, "facts": 4, "essential": 3, "runsMustState": 2, "nonDefects": 0,
                                       "defects": 1}
    assert reference_set["note"] == "Frozen from named human decisions; hashes identify bytes, not approval."
    assert "Entrypoints: train.py, lib/model.py\nArguments: none\n" in \
        (frozen_dir(world) / "prompts/skill/pilot-demo.txt").read_text(encoding="utf-8")
    assert run(world, "check-frozen", corpus=None)[0] == 0


# --------------------------------------------------------------------------------------------
# Round 3: merge-aware history, erased campaigns and partial clones (synthetic data only)


def branch_name(world: wd.World) -> str:
    return git(world.root, "rev-parse", "--abbrev-ref", "HEAD").strip()


def merge(world: wd.World, branch: str, *, resolve: str | None = None, paths: tuple[str, ...] = ()) -> None:
    """Merge ``branch``; on a conflict take ``resolve`` ("ours" or "theirs") for ``paths`` and commit."""
    result = subprocess.run(["git", "-C", str(world.root), "merge", "--quiet", "--no-edit", "--no-ff", branch],
                            capture_output=True, env=git_env(), check=False)
    if result.returncode:
        assert resolve is not None, result.stdout + result.stderr
        git(world.root, "checkout", f"--{resolve}", "--", *paths)
        commit_all(world, f"synthetic merge of {branch}, conflict resolved to {resolve}")


@pytest.mark.parametrize("resolve", ["ours", "theirs"])
def test_a_merge_cannot_replace_a_recorded_summary(tmp_path: Path, verified, resolve: str) -> None:
    """Two branches that both record a summary leave two contents in the history, whichever side a
    merge keeps (INTEGRITY3-1: an add/add conflict)."""
    world = frozen_world(tmp_path)
    git_world(world)
    synthetic_candidate(world)
    commit_all(world, "synthetic capture")
    main = branch_name(world)
    git(world.root, "checkout", "--quiet", "-b", "side")
    synthetic_summary(world, "go")
    commit_all(world, "synthetic go on a side branch")
    git(world.root, "checkout", "--quiet", main)
    synthetic_summary(world, "stop")
    commit_all(world, "synthetic stop on main")
    names = ("stage1-summary.json", "stage1-summary.md")
    merge(world, "side", resolve=resolve, paths=tuple(f"{wd.PILOT_REL}/pilot-99/{name}" for name in names))
    code, out = run(world, "check-frozen")
    assert code == 1, out
    for name in names:
        assert f"evals/workflow/pilot/pilot-99/{name} was committed with 2 different contents (" in out, out
    assert "the owner records invalidation.md and a new campaign supersedes this one" in out


def test_two_merged_recordings_are_settled_by_invalidation_and_a_new_campaign(tmp_path: Path, verified) -> None:
    """The finding cannot be undone in history, so once the owner invalidated the campaign and a new
    campaign supersedes it, it is kept as a note (the remedy the message names)."""
    world = frozen_world(tmp_path)
    git_world(world)
    synthetic_candidate(world)
    commit_all(world, "synthetic capture")
    main = branch_name(world)
    git(world.root, "checkout", "--quiet", "-b", "side")
    synthetic_summary(world, "invalid")
    commit_all(world, "synthetic recording on a side branch")
    git(world.root, "checkout", "--quiet", main)
    synthetic_summary(world, "stop")
    commit_all(world, "synthetic recording on main")
    names = tuple(f"{wd.PILOT_REL}/pilot-99/{name}" for name in ("stage1-summary.json", "stage1-summary.md"))
    merge(world, "side", resolve="ours", paths=names)
    assert run(world, "check-frozen")[0] == 1
    (frozen_dir(world) / "invalidation.md").write_text(
        f"# Invalidation: pilot-99\nReviewer: {REVIEWER}\nDate: {DATE}\nScope: campaign\nReason: synthetic\n",
        encoding="utf-8")
    code, out = run(world, "freeze", "--campaign", "pilot-100", "--write", "--frozen-at", FROZEN_AT,
                    "--supersede-reason", "two recordings were merged (synthetic)")
    assert code == 0, out
    commit_all(world, "synthetic invalidation and new campaign")
    code, out = run(world, "check-frozen")
    assert code == 0, out
    assert "check-frozen: pilot-99 (invalidated): evals/workflow/pilot/pilot-99/stage1-summary.json was committed " \
           "with 2 different contents" in out, out


def test_an_ordinary_merge_of_a_recorded_summary_passes(tmp_path: Path, verified) -> None:
    """A pull-request merge records the same content twice (the branch commit and the merge): one
    content, no finding."""
    world = frozen_world(tmp_path)
    git_world(world)
    main = branch_name(world)
    git(world.root, "checkout", "--quiet", "-b", "pilot")
    synthetic_candidate(world)
    synthetic_summary(world, "stop")
    commit_all(world, "synthetic capture and stop on a branch")
    git(world.root, "checkout", "--quiet", main)
    (world.root / "main.txt").write_text("synthetic\n", encoding="utf-8")
    commit_all(world, "synthetic main")
    merge(world, "pilot")
    code, out = run(world, "check-frozen")
    assert code == 0 and "(final summary recorded): hashes intact." in out, out
    assert "without the full Git history" not in out and "cannot read" not in out, out


def test_a_freeze_recorded_inside_a_merge_is_bound_to_that_commit(tmp_path: Path, verified) -> None:
    """freeze.json first recorded by a merge commit is found, so a later edit fails (INTEGRITY3-1)."""
    world = make_world(tmp_path)
    complete_world(world)
    git_world(world)
    main = branch_name(world)
    git(world.root, "checkout", "--quiet", "-b", "side")
    (world.root / "side.txt").write_text("synthetic\n", encoding="utf-8")
    commit_all(world, "synthetic side")
    git(world.root, "checkout", "--quiet", main)
    (world.root / "main.txt").write_text("synthetic\n", encoding="utf-8")
    commit_all(world, "synthetic main")
    git(world.root, "merge", "--quiet", "--no-ff", "--no-commit", "side")
    assert run(world, "freeze", "--campaign", "pilot-99", "--write", "--frozen-at", FROZEN_AT)[0] == 0
    commit_all(world, "synthetic merge that records the freeze")
    code, out = run(world, "check-frozen")
    assert code == 0 and "not verified" not in out, out
    path = frozen_dir(world) / "freeze.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["tasksManifest"]["sha256"] = "0" * 64
    path.write_bytes(er.canonical_json(value))
    commit_all(world, "synthetic edit of freeze.json")
    code, out = run(world, "check-frozen")
    assert code == 1 and "evals/workflow/pilot/pilot-99/freeze.json differs from the version committed in" in out, out
    assert "evals/workflow/pilot/pilot-99/freeze.json was committed with 2 different contents" in out


def test_a_removal_hidden_by_a_merge_is_still_found(tmp_path: Path, verified) -> None:
    """A summary recorded and removed on main, then hidden by merging main into an older branch that
    main fast-forwards to, is still reported (INTEGRITY3-1, the default log shows nothing here)."""
    world = frozen_world(tmp_path)
    git_world(world)
    synthetic_candidate(world)
    commit_all(world, "synthetic capture")
    main = branch_name(world)
    git(world.root, "branch", "older")
    synthetic_summary(world, "stop")
    commit_all(world, "synthetic stop")
    stop = git(world.root, "rev-parse", "HEAD").strip()
    for name in ("stage1-summary.json", "stage1-summary.md"):
        git(world.root, "rm", "--quiet", str(frozen_dir(world) / name))
    git(world.root, "commit", "--quiet", "-m", "synthetic removal")
    git(world.root, "checkout", "--quiet", "older")
    (world.root / "older.txt").write_text("synthetic\n", encoding="utf-8")
    commit_all(world, "synthetic older work")
    git(world.root, "merge", "--quiet", "--no-edit", main)
    git(world.root, "checkout", "--quiet", main)
    git(world.root, "merge", "--quiet", "--ff-only", "older")
    rel = f"{wd.PILOT_REL}/pilot-99/stage1-summary.json"
    assert git(world.root, "log", "--format=%H", "--", rel).strip() == ""  # hidden from the default log
    code, out = run(world, "check-frozen")
    assert code == 1 and f"{rel} was committed in" in out and "is missing now (a recorded summary is final)" in out, out
    # The same world with the summary restored byte for byte is intact: nothing changed.
    git(world.root, "checkout", "--quiet", stop, "--", f"{wd.PILOT_REL}/pilot-99")
    commit_all(world, "synthetic restore")
    code, out = run(world, "check-frozen")
    assert code == 0 and "(final summary recorded): hashes intact." in out, out


def test_a_replaced_candidate_fails_check_frozen(tmp_path: Path, verified) -> None:
    """candidate.json is final once committed: removed and re-added, or edited in place (DISTCI3-2)."""
    world = frozen_world(tmp_path)
    git_world(world)
    first = synthetic_candidate(world)
    commit_all(world, "synthetic capture")
    path = frozen_dir(world) / "candidate.json"
    path.write_bytes(first.replace(b"synthetic candidate for tests", b"another synthetic candidate"))
    commit_all(world, "synthetic in-place edit")
    code, out = run(world, "check-frozen")
    rel = "evals/workflow/pilot/pilot-99/candidate.json"
    assert code == 1 and f"{rel} was committed with 2 different contents" in out, out
    assert f"{rel} differs from the version first committed in" in out
    path.write_bytes(first)
    commit_all(world, "synthetic restore of the first candidate")
    code, out = run(world, "check-frozen")
    assert code == 1 and f"{rel} was committed with 2 different contents" in out, out


def test_an_erased_campaign_fails_and_blocks_a_new_freeze(tmp_path: Path, verified) -> None:
    """Deleting a captured campaign and restoring the pre-freeze tasks.json is found by check-frozen,
    and a new freeze is refused (INTEGRITY3-2)."""
    world = make_world(tmp_path)
    complete_world(world)
    tasks = world.root / "evals/workflow/tasks.json"
    pre_freeze = tasks.read_bytes()
    assert run(world, "freeze", "--campaign", "pilot-99", "--write", "--frozen-at", FROZEN_AT)[0] == 0
    git_world(world)
    synthetic_candidate(world)
    synthetic_summary(world, "stop")
    commit_all(world, "synthetic capture and Stage 1 stop")
    assert run(world, "check-frozen")[0] == 0
    git(world.root, "rm", "-r", "--quiet", str(frozen_dir(world)))
    tasks.write_bytes(pre_freeze)
    commit_all(world, "synthetic erasure of pilot-99")
    world.reload_manifest()
    code, out = run(world, "check-frozen")
    assert code == 1 and "check-frozen: evals/workflow/pilot/pilot-99/freeze.json was committed in " in out, out
    assert "is missing now; a committed campaign is immutable and is never erased" in out
    assert "nothing to check" not in out
    out = refused(world)
    assert "the Git history holds committed campaign(s) pilot-99 under evals/workflow/pilot; a committed campaign is " \
           "immutable and is never erased" in out, out
    # An uncommitted freeze in a fresh repository is not affected.
    fresh = make_world(tmp_path / "fresh")
    complete_world(fresh)
    git_world(fresh)
    code, out = run(fresh, "freeze", "--campaign", "pilot-99", "--frozen-at", FROZEN_AT)
    assert code == 0, out


def partial_clone(world: wd.World, target: Path, spec: str) -> wd.World:
    git(world.root, "config", "uploadpack.allowFilter", "true")
    subprocess.run(["git", "clone", "--quiet", f"--filter={spec}", "--no-checkout", world.root.resolve().as_uri(),
                    str(target)], check=True, capture_output=True, env=git_env())
    subprocess.run(["git", "-C", str(target), "checkout", "--quiet"], check=True, capture_output=True, env=git_env())
    return wd.World(target, world.corpus)


@pytest.mark.parametrize("spec", ["tree:0", "blob:none"])
def test_a_partial_clone_says_which_history_checks_did_not_run(tmp_path: Path, verified, spec: str) -> None:
    """A partial clone is not a full history: check-frozen names the unverified checks instead of
    reading "never committed" from a failed git log, and a supersede is refused (INTEGRITY3-5)."""
    world = frozen_world(tmp_path / "a")
    git_world(world)
    synthetic_candidate(world)
    synthetic_summary(world, "stop")
    commit_all(world, "synthetic capture")
    for name in ("stage1-summary.json", "stage1-summary.md"):
        git(world.root, "rm", "--quiet", str(frozen_dir(world) / name))
    git(world.root, "commit", "--quiet", "-m", "synthetic removal")
    assert run(world, "check-frozen")[0] == 1
    clone = partial_clone(world, tmp_path / "clone", spec)
    assert er.history_limit(clone.root) is not None
    code, out = run(clone, "check-frozen")
    assert "check-frozen: pilot-99: not verified without the full Git history (this is a partial clone" in out, out
    code, out = run(clone, "freeze", "--campaign", "pilot-100", "--frozen-at", FROZEN_AT, "--supersede-reason",
                    "synthetic reason")
    assert code == 1 and "cannot tell whether pilot-99 was ever captured: this is a partial clone" in out, out


# --------------------------------------------------------------------------------------------
# Round 3: owner messages (synthetic decisions only)


def adoption_world(tmp_path: Path) -> tuple[wd.World, str]:
    """A second review that adds essential demo-s-h01, and a primary with its own essential demo-h01."""
    world = make_world(tmp_path)
    added = ["## Added fact demo-s-h01", "Wording: The synthetic loop also clips gradients at one.",
             "Basis: observed", "Essential: yes", "Anchors: train.py:10", ""]
    second = insert_before(fill_header(wd.task_template(world, "pilot-demo", second=True), SECOND), "## Task", added)
    write(world, "pilot-demo.second.md", complete(second))
    own = ["## Added fact demo-h01", "Wording: The synthetic loop clips gradients at one.", "Basis: observed",
           "Essential: yes", "Anchors: train.py:10", "Reason: adopted from the second review (synthetic)", ""]
    return world, insert_before(accept_all(world, "pilot-demo"), "## Disagreements", own)


def resolve(world: wd.World, primary: str, *lines: str) -> str:
    write(world, "pilot-demo.md", complete(primary.replace("## Disagreements\n",
                                                           "## Disagreements\n" + "".join(f"{l}\n" for l in lines))))
    return run(world, "check", "pilot-demo")[1]


NAMED = ('ERROR Disagreements: demo-s-h01: the resolution names your added item demo-h01, so it is read as not '
         'adopted. Write "demo-s-h01: adopted as demo-h01 -- <why>" to adopt it, or remove demo-h01 from this line if '
         'it is not adopted.')


@pytest.mark.parametrize("line, message", [
    ("demo-s-h01: adopt as demo-h01 -- same fact (synthetic).", NAMED),
    ("demo-s-h01: adpoted as demo-h01 -- same fact (synthetic).", NAMED),
    ("demo-s-h01: adopting it, same fact (synthetic).",
     'ERROR Disagreements: demo-s-h01: the resolution starts with "adopting", which reads like "adopted" but is not the '
     'adoption form. To adopt it, write "demo-s-h01: adopted as <your ID> -- <why>"; otherwise start the resolution '
     'with a word other than "adopting", for example "demo-s-h01: not adopted -- <why>".'),
    ("demo-s-h01: same as demo-h01, merged (synthetic).", NAMED),
    # A sentence-final "." or "_" is not part of the ID (OWNERUX4-3).
    ("demo-s-h01: same as demo-h01.", NAMED),
    ("demo-s-h01: not adopted, same as my demo-h01.", NAMED),
    ("demo-s-h01: not adopted -- duplicates demo-h01.", NAMED),
    ("demo-s-h01: not adopted -- duplicates demo-h01_", NAMED),
])
def test_a_mistyped_adoption_is_an_error(tmp_path: Path, verified, line: str, message: str) -> None:
    """A resolution that names the primary's own addition of the same kind, or starts like "adopted", is
    never frozen as a plain non-adoption (OWNERUX3-2, OWNERUX4-3, OWNERUX4-7)."""
    world, primary = adoption_world(tmp_path)
    out = resolve(world, primary, line)
    assert message in out, out
    assert "ready to freeze" not in out
    out = resolve(world, primary, "demo-s-h01: adopted as demo-h01 -- same fact (synthetic).")
    assert "pilot-demo: 0 error(s), 0 to do; ready to freeze." in out, out


def test_a_case_only_duplicate_resolution_is_an_error(tmp_path: Path, verified) -> None:
    """Resolution keys are case-insensitive, so a second line never silently replaces the first (OWNERUX3-3)."""
    world, primary = adoption_world(tmp_path)
    out = resolve(world, primary, "demo-s-h01: adopted as demo-h01 -- same fact (synthetic).",
                  "DEMO-S-H01: not adopted (synthetic).")
    assert 'ERROR Disagreements: "DEMO-S-H01" appears twice (first on line ' in out and "Keep one." in out, out
    result = wd.check_path(world, world.root / wd.DECISIONS_REL / "pilot-demo.md")[0].result
    assert result.disputes[0]["adoptedAs"] == "demo-h01"


def test_a_mistyped_resolution_id_lists_the_open_items(tmp_path: Path, verified) -> None:
    """An unknown key names the items still open and the closest one (OWNERUX3-9)."""
    world, primary = adoption_world(tmp_path)
    out = resolve(world, primary, "demo-s-h1: adopted as demo-h01 -- same fact (synthetic).")
    assert 'ERROR Disagreements: "demo-s-h1" is not an item that disagrees with the second review (still open: ' \
           'demo-s-h01); did you mean "demo-s-h01"? Correct the ID, or delete this line.' in out, out


def test_adopting_a_candidate_item_explains_the_non_adoption_form(tmp_path: Path, verified) -> None:
    """"adopted as <candidate ID>" is told that a duplicate of a candidate item is not an adoption (OWNERUX3-7)."""
    world, primary = adoption_world(tmp_path)
    out = resolve(world, primary, "demo-s-h01: adopted as demo-f01 -- already covered (synthetic).")
    assert 'demo-s-h01: "adopted as demo-f01" must name the section you added for it in this file' in out, out
    assert 'A candidate item is already in your reference: if the addition duplicates it, write "demo-s-h01: <why it ' \
           'is not adopted>" (for example "same as demo-f01") without the word "adopted".' in out, out
    out = resolve(world, primary, "demo-s-h01: adopted in substance by demo-f01, no new item (synthetic).")
    assert '(for example "same as <candidate ID>") without the word "adopted".' in out, out
    out = resolve(world, primary, "demo-s-h01: same as demo-f01, not a new fact (synthetic).")
    assert "pilot-demo: 0 error(s), 0 to do; ready to freeze." in out, out


def test_the_high_severity_note_suggests_the_next_unused_second_review_id(shared_world: wd.World) -> None:
    """The NOTE never suggests an s-d ID the second review already uses (OWNERUX3-8)."""
    def defect(ident: str) -> list[str]:
        return [f"## Defect {ident}", "Wording: A high synthetic defect.", "Severity: high", "Anchors: lib/model.py:5",
                "Counter-evidence: none (synthetic)", "Reason: synthetic", ""]

    primary = insert_before(accept_all(shared_world, "pilot-demo"), "## Disagreements",
                            defect("demo-d01") + defect("demo-d02"))
    primary = primary.replace("## Disagreements\n", "## Disagreements\ndemo-s-d01: adopted as demo-d01 -- the same "
                                                    "defect (synthetic)\n")
    second = insert_before(fill_header(wd.task_template(shared_world, "pilot-demo", second=True), SECOND), "## Task",
                           defect("demo-s-d01"))
    second_check = wd.check_reference(shared_world, second.encode("utf-8"), "pilot-demo.second.md")
    checked = wd.check_reference(shared_world, primary.encode("utf-8"), "pilot-demo.md", second=second_check)
    notes = [p.message for p in checked.report.problems if p.level == "NOTE"]
    assert len(notes) == 1 and '"## Defect demo-s-d02"' in notes[0] and \
        '"demo-s-d02: adopted as demo-d02 -- <why>"' in notes[0], notes


def test_a_late_second_review_keeps_the_primary_frozen_in_check(tmp_path: Path, verified) -> None:
    """A complete second review added after the freeze does not tell the owner to edit the frozen
    primary; check-frozen points at the added file (OWNERUX3-4)."""
    world = frozen_world(tmp_path)
    second = decide(fill_header(wd.task_template(world, "pilot-demo", second=True), SECOND), "Fact demo-f02", "reject",
                    "Reason: synthetic")
    path = write(world, "pilot-demo.second.md", complete(second))
    code, out = run(world, "check", "pilot-demo")
    assert "pilot-demo: 0 error(s), 0 to do; frozen in pilot-99." in out, out
    assert "NOTE  Disagreements: for a new campaign (evals/workflow/decisions/pilot-demo.second.md was added after the " \
           "freeze of pilot-99): demo-f02:" in out, out
    assert "this file is still the version frozen in pilot-99. To keep pilot-99, move " \
           "evals/workflow/decisions/pilot-demo.second.md out of evals/workflow/decisions/ (keep it for a new " \
           "campaign" in out, out
    assert "NOTE  Task: for a new campaign (evals/workflow/decisions/pilot-demo.second.md was added after the freeze " \
           "of pilot-99): Review is complete, but the second review added 1 item(s) to resolve" in out, out
    assert "TODO" not in out.split("pilot-demo: 0 error(s)")[0], out
    code, out = run(world, "check-frozen")
    assert code == 1 and "Next: move evals/workflow/decisions/pilot-demo.second.md out of evals/workflow/decisions/ to " \
                         "keep pilot-99 (keep it for a new campaign), or freeze a new campaign " \
                         "(evals/workflow/pilot/README.md)" in out, out
    # The freeze of a new campaign still sees the unresolved disagreement.
    code, out = run(world, "freeze", "--campaign", "pilot-100", "--frozen-at", FROZEN_AT, "--supersede-reason", "x")
    assert code == 1 and "evals/workflow/decisions/pilot-demo.md: 0 error(s), 2 to do" in out, out
    path.unlink()
    assert run(world, "check-frozen")[0] == 0


@pytest.mark.parametrize("change", ["note", "crlf"])
def test_a_byte_change_after_the_freeze_offers_the_restore(tmp_path: Path, verified, change: str) -> None:
    """A ">" note or a CRLF re-save after the freeze is named with the restore command where Git holds the
    frozen bytes, never otherwise, and the file is not called ready to freeze (OWNERUX3-5, OWNERUX4-1)."""
    world = frozen_world(tmp_path)
    rel = "evals/workflow/decisions/pilot-demo.md"
    path = world.root / rel
    raw = path.read_bytes()
    edited = raw.replace(b"\n", b"\r\n") if change == "crlf" else raw + b"> frozen, do not edit (synthetic)\n"
    path.write_bytes(edited)
    code, out = run(world, "check", "pilot-demo")
    assert "If you did not mean to change a decision, restore the frozen bytes (no git command: the repository root " \
           "is not a Git work tree. Undo the edit in your editor): frozen decision files are compared byte for byte, " \
           'including ">" lines and line endings.' in out, out
    assert "pilot-demo: 0 error(s), 0 to do; changed after the freeze of pilot-99." in out and "ready to freeze" not in out
    code, out = run(world, "check-frozen")
    assert code == 1 and f"{rel} changed after the freeze of pilot-99; a changed decision needs a new campaign " \
                         "(evals/workflow/pilot/README.md); if no decision changed, restore the frozen bytes (no git " \
                         "command" in out, out
    # With the freeze committed, the index holds the frozen bytes, and the offered command restores them.
    path.write_bytes(raw)
    git_world(world)
    path.write_bytes(edited)
    code, out = run(world, "check", "pilot-demo")
    assert f"restore the frozen bytes (git checkout -- {rel}): frozen decision files" in out, out
    code, out = run(world, "check-frozen")
    assert code == 1 and f"restore the frozen bytes (git checkout -- {rel}): frozen files" in out, out
    git(world.root, "checkout", "--", rel)
    assert path.read_bytes() == raw and run(world, "check-frozen")[0] == 0


# --------------------------------------------------------------------------------------------
# Round 4 (synthetic decisions only)


def test_the_restore_advice_never_offers_the_committed_template(tmp_path: Path, verified) -> None:
    """Pending templates committed, decisions filled and frozen but not committed, then a CRLF re-save:
    "git checkout -- <file>" would restore the pending template, so no git command is offered (OWNERUX4-1)."""
    world = make_world(tmp_path)
    write(world, "pilot-demo.md", wd.task_template(world, "pilot-demo"))
    write(world, "pilot-book.md", wd.task_template(world, "pilot-book"))
    write(world, "run-policy.md", wd.policy_template(world))
    git_world(world)  # the pending templates are committed
    complete_world(world)
    assert run(world, "freeze", "--campaign", "pilot-99", "--write", "--frozen-at", FROZEN_AT)[0] == 0
    world.reload_manifest()
    path = world.root / wd.DECISIONS_REL / "pilot-demo.md"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    for command in ("check", "check-frozen"):
        code, out = run(world, command, *(["pilot-demo"] if command == "check" else []))
        assert "no git command: Git does not hold these bytes because the freeze of pilot-99 is not committed yet. " \
               "Undo the edit in your editor; if you cannot, delete evals/workflow/pilot/pilot-99/, restore the " \
               "pre-freeze evals/workflow/tasks.json (git checkout HEAD -- evals/workflow/tasks.json) and freeze " \
               "again" in out, (command, out)
        assert "git checkout -- evals/workflow/decisions" not in out, (command, out)


def test_the_restore_advice_names_the_commit_after_a_committed_change_or_removal(tmp_path: Path, verified) -> None:
    """Once the change or the removal is committed, the offered command names the commit that holds the
    frozen bytes, and a removed file is never told to start from a template (OWNERUX4-1, SPECDOCS4-4)."""
    world = frozen_world(tmp_path)
    git_world(world)
    freeze_commit = git(world.root, "rev-parse", "HEAD").strip()
    rel = "evals/workflow/decisions/pilot-demo.md"
    path = world.root / rel
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b"\n", b"\r\n"))
    commit_all(world, "synthetic CRLF re-save")
    code, out = run(world, "check-frozen")
    command = f"git checkout {freeze_commit[:12]} -- {rel}"
    assert code == 1 and f"restore the frozen bytes ({command}): frozen files" in out, out
    git(world.root, "checkout", freeze_commit, "--", rel)
    assert path.read_bytes() == raw and run(world, "check-frozen")[0] == 0
    commit_all(world, "synthetic restore")
    git(world.root, "rm", "--quiet", rel)
    commit_all(world, "synthetic removal")
    code, out = run(world, "check-frozen")
    assert code == 1 and f"{rel} (missing) changed after the freeze of pilot-99" in out, out
    assert f"restore the frozen bytes ({command})" in out and f"Next: restore the frozen {rel} ({command}) to keep " \
                                                             "pilot-99" in out, out
    assert "template pilot-demo" not in out, out
    git(world.root, "checkout", freeze_commit, "--", rel)
    assert run(world, "check-frozen")[0] == 0


def second_review_world(tmp_path: Path) -> wd.World:
    """pilot-demo frozen with a second review that rejects demo-f02 and a primary that resolved it."""
    world = make_world(tmp_path)
    complete_world(world)
    second = decide(fill_header(wd.task_template(world, "pilot-demo", second=True), SECOND), "Fact demo-f02", "reject",
                    "Reason: synthetic")
    write(world, "pilot-demo.second.md", complete(second))
    write(world, "pilot-demo.md", complete(accept_all(world, "pilot-demo")).replace(
        "## Disagreements\n", "## Disagreements\ndemo-f02: kept after discussion (synthetic)\n"))
    code, out = run(world, "freeze", "--campaign", "pilot-99", "--write", "--frozen-at", FROZEN_AT)
    assert code == 0, out
    world.reload_manifest()
    git_world(world)
    return world


@pytest.mark.parametrize("how", ["edited", "removed"])
def test_a_changed_or_removed_second_review_keeps_the_primary_frozen_in_check(tmp_path: Path, verified,
                                                                             how: str) -> None:
    """An edited or removed frozen second review never tells the owner to edit the frozen primary; check and
    check-frozen point at the second-review file and its restore (OWNERUX4-4)."""
    world = second_review_world(tmp_path)
    rel = "evals/workflow/decisions/pilot-demo.second.md"
    path = world.root / rel
    raw = path.read_bytes()
    if how == "edited":
        path.write_bytes(raw.replace(b"Decision: reject\nReason: synthetic\n", b"Decision: accept\n"))
        cause = f"{rel} changed after the freeze of pilot-99"
        message = '"demo-f02" does not disagree with the second review; delete this line.'
    else:
        path.unlink()
        cause = f"{rel}, frozen in pilot-99, is missing"
        message = '"demo-f02": there is no second review (pilot-demo.second.md) to disagree with; delete this line.'
    code, out = run(world, "check", "pilot-demo")
    assert f"NOTE  Disagreements: for a new campaign ({cause}): {message}" in out, out
    assert f"this file is still the version frozen in pilot-99. To keep pilot-99, restore" in out and \
        f"(git checkout -- {rel})" in out, out
    assert "pilot-demo: 0 error(s), 0 to do; frozen in pilot-99." in out, out
    code, out = run(world, "check-frozen")
    assert code == 1 and f"Next: restore the frozen {rel} (git checkout -- {rel}) to keep pilot-99, or freeze a new " \
                         "campaign" in out, out
    assert "Next: python tools/workflow_eval.py check pilot-demo" not in out, out
    git(world.root, "checkout", "--", rel)
    assert run(world, "check-frozen")[0] == 0


def test_an_edited_proposal_line_is_noted_with_the_ledger_text(tmp_path: Path) -> None:
    """The freeze takes each proposal from the candidate ledger; an edited or removed ">" proposal line is
    noted with the ledger's text, while added notes stay free (INTEGRITY4-4)."""
    world = make_world(tmp_path)
    template = wd.task_template(world, "pilot-demo")
    pristine = wd.check_reference(world, template.encode("utf-8"), "pilot-demo.md")
    assert not [p for p in pristine.report.problems if p.level == "NOTE"]
    claim = "> Claim: The synthetic model width comes from lib/model.py constants."
    noted = template.replace("## Fact demo-f02\n", "## Fact demo-f02\n> my own note (synthetic)\n")
    assert not [p for p in wd.check_reference(world, noted.encode("utf-8"), "pilot-demo.md").report.problems
                if p.level == "NOTE"]
    for edited in (template.replace(claim, "> Claim: The synthetic model width is read from the command line."),
                   template.replace(claim + "\n", "")):
        checked = wd.check_reference(world, edited.encode("utf-8"), "pilot-demo.md")
        notes = [(p.section, p.message) for p in checked.report.problems if p.level == "NOTE"]
        assert notes == [("Fact demo-f02", 'the ">" proposal lines under this heading are missing or differ from the '
                          "candidate ledger pilot-demo.json, and accept takes the ledger's proposal: \"Claim: The "
                          'synthetic model width comes from lib/model.py constants.". If someone edited them, restore the '
                          "lines the tool wrote (python tools/workflow_eval.py template --show pilot-demo).")], notes


def test_a_superseding_freeze_refuses_while_a_committed_campaign_is_missing(tmp_path: Path, verified) -> None:
    """Erasing a captured superseding campaign and pointing tasks.json at an older one does not let a new
    freeze skip it: the supersede path checks the committed campaigns too (SPECDOCS4-2)."""
    world = make_world(tmp_path)
    complete_world(world)
    tasks = world.root / "evals/workflow/tasks.json"
    assert run(world, "freeze", "--campaign", "pilot-98", "--write", "--frozen-at", FROZEN_AT)[0] == 0
    git_world(world)
    names_98 = tasks.read_bytes()
    world.reload_manifest()
    code, out = run(world, "freeze", "--campaign", "pilot-99", "--write", "--frozen-at", FROZEN_AT,
                    "--supersede-reason", "synthetic reason")
    assert code == 0, out
    world.reload_manifest()
    synthetic_candidate(world, "pilot-99")
    commit_all(world, "synthetic pilot-99 freeze and capture")
    assert run(world, "check-frozen")[0] == 0
    git(world.root, "rm", "-r", "--quiet", str(frozen_dir(world, "pilot-99")))
    tasks.write_bytes(names_98)
    world.reload_manifest()
    code, out = run(world, "freeze", "--campaign", "pilot-97", "--frozen-at", FROZEN_AT, "--supersede-reason",
                    "synthetic reason 2")
    assert code == 1 and "the Git history holds committed campaign(s) under evals/workflow/pilot that the campaign " \
                         "pilot-98 named in evals/workflow/tasks.json does not account for (pilot-99 was committed " \
                         "and is missing now)" in out, out
    assert not frozen_dir(world, "pilot-97").exists()


def test_a_high_severity_note_never_suggests_a_resolved_second_review_defect(tmp_path: Path, verified) -> None:
    """With the second review's demo-s-d01 resolved as not adopted, the note names demo-s-d02 and never
    demo-s-d01 (OWNERUX4-2, SPECDOCS4-3)."""
    world = make_world(tmp_path)
    defect = ["## Defect demo-d01", "Wording: A high synthetic defect.", "Severity: high", "Anchors: lib/model.py:5",
              "Counter-evidence: none (synthetic)", "Reason: synthetic", ""]
    theirs = ["## Defect demo-s-d01", "Wording: An unrelated low synthetic defect.", "Severity: low",
              "Anchors: lib/model.py:3", "Counter-evidence: none (synthetic)", "Reason: synthetic", ""]
    second = insert_before(fill_header(wd.task_template(world, "pilot-demo", second=True), SECOND), "## Task", theirs)
    write(world, "pilot-demo.second.md", complete(second))
    primary = insert_before(accept_all(world, "pilot-demo"), "## Disagreements", defect)
    out = resolve(world, primary, "demo-s-d01: not a defect of this code -- unrelated (synthetic)")
    notes = [line for line in out.splitlines() if "NOTE  Defect demo-d01" in line]
    assert len(notes) == 1 and '"## Defect demo-s-d02"' in notes[0] and "demo-s-d01" not in notes[0], out


def test_a_non_adoption_naming_another_kind_or_worded_otherwise_passes(tmp_path: Path, verified) -> None:
    """Only an added item of the same kind can be adopted, so naming an added fact in a defect's
    resolution is not an error; a first word like "adopted" is told what to change (OWNERUX4-7)."""
    world, primary = adoption_world(tmp_path)
    second = (world.root / wd.DECISIONS_REL / "pilot-demo.second.md").read_text(encoding="utf-8")
    write(world, "pilot-demo.second.md", insert_before(second, "## Task", [
        "## Defect demo-s-d01", "Wording: A medium synthetic defect.", "Severity: medium", "Anchors: lib/model.py:3",
        "Counter-evidence: none (synthetic)", "Reason: synthetic", ""]))
    adopted = "demo-s-h01: adopted as demo-h01 -- same fact (synthetic)."
    out = resolve(world, primary, adopted, "demo-s-d01: not a defect; the behaviour is the resume path my demo-h01 "
                                           "describes (synthetic)")
    assert "pilot-demo: 0 error(s), 0 to do; ready to freeze." in out, out
    out = resolve(world, primary, adopted, "demo-s-d01: Adoption declined -- the width is intended (synthetic)")
    assert 'demo-s-d01: the resolution starts with "Adoption", which reads like "adopted" but is not the adoption ' \
           'form. To adopt it, write "demo-s-d01: adopted as <your ID> -- <why>"; otherwise start the resolution with ' \
           'a word other than "Adoption", for example "demo-s-d01: not adopted -- <why>".' in out, out


def gitlink_version(world: wd.World, rel: str, restore: bytes) -> None:
    """Commit ``rel`` as a gitlink (a submodule entry naming a commit), then commit ``restore`` again."""
    head = git(world.root, "rev-parse", "HEAD").strip()
    git(world.root, "rm", "--quiet", "--cached", rel)
    git(world.root, "update-index", "--add", "--cacheinfo", f"160000,{head},{rel}")
    git(world.root, "commit", "--quiet", "-m", "synthetic gitlink at the path")
    git(world.root, "rm", "--quiet", "--cached", rel)
    (world.root / rel).write_bytes(restore)
    git(world.root, "add", rel)
    git(world.root, "commit", "--quiet", "-m", "synthetic restore of the replaced bytes")


@pytest.mark.parametrize("number, first, then", [("1", "stop", "go"), ("2", "targets-missed", "targets-met"),
                                                 ("candidate", "", "")])
def test_a_gitlink_version_never_hides_a_replaced_final_file(tmp_path: Path, verified, number: str, first: str,
                                                             then: str) -> None:
    """A final file (stage summary, candidate.json) replaced after it was recorded stays a problem when a
    gitlink version of the same path is added to the history (INTEGRITY4-1)."""
    world = frozen_world(tmp_path)
    git_world(world)
    synthetic_candidate(world)
    if number == "2":
        synthetic_summary(world, "go")
    if number != "candidate":
        synthetic_summary(world, first, number=number)
    commit_all(world, "synthetic capture")
    assert run(world, "check-frozen")[0] == 0
    if number == "candidate":
        path = frozen_dir(world) / "candidate.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["note"] = "a second, hand-written candidate (synthetic)"
        path.write_bytes(er.canonical_json(value))
        names = ["candidate.json"]
    else:
        synthetic_summary(world, then, number=number)
        names = [f"stage{number}-summary.json", f"stage{number}-summary.md"]
    commit_all(world, "synthetic replacement")
    code, out = run(world, "check-frozen")
    assert code == 1 and "different contents" in out, out
    for name in names:
        rel = f"evals/workflow/pilot/pilot-99/{name}"
        gitlink_version(world, rel, (world.root / rel).read_bytes())
    code, out = run(world, "check-frozen")
    assert code == 1 and "different contents" in out, out
    assert f"evals/workflow/pilot/pilot-99/{names[0]} was committed as a gitlink (a submodule commit) in" in out, out
    assert "not verified: git cannot read the history" not in out, out


LOG_CONFIG = "[log]\n\tfollow = true\n\tdiffMerges = combined\n\tshowRoot = false\n"


def test_history_queries_ignore_the_users_log_configuration(tmp_path: Path, verified,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """log.follow, log.diffMerges and log.showRoot never change what the history lists: a copied
    freeze.json, a version that exists only in a merge and a root-commit addition are all found, and an
    invalidation plus a superseding campaign passes check-frozen (DISTCI4-2)."""
    config = tmp_path / "gitconfig"
    config.write_text(LOG_CONFIG, encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet")
    base = {"p/a/freeze.json": b'{"campaign": "a", "files": {"x": 1, "y": 2, "z": 3}, "note": "synthetic"}\n'}
    for rel, data in base.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_bytes(data)
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "root adds a (synthetic)")
    (repo / "p/b").mkdir()
    (repo / "p/b/freeze.json").write_bytes(base["p/a/freeze.json"].replace(b'"a"', b'"b"'))
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "copy-like b (synthetic)")
    main = git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    git(repo, "checkout", "--quiet", "-b", "side")
    (repo / "p/side.txt").write_bytes(b"side\n")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "side (synthetic)")
    git(repo, "checkout", "--quiet", main)
    git(repo, "merge", "--quiet", "--no-ff", "--no-commit", "side")
    (repo / "p/b/freeze.json").write_bytes(b'{"campaign": "b", "evil": true}\n')
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "merge with a version only here (synthetic)")
    (repo / "p/b/freeze.json").write_bytes(base["p/a/freeze.json"].replace(b'"a"', b'"b"'))
    git(repo, "commit", "--quiet", "-am", "restore b (synthetic)")
    expected = (er.path_history(repo, "p/a/freeze.json"), er.path_history(repo, "p/b/freeze.json"),
                er.committed_paths(repo, "p"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    root_history, copied, paths = (er.path_history(repo, "p/a/freeze.json"), er.path_history(repo, "p/b/freeze.json"),
                                   er.committed_paths(repo, "p"))
    assert (root_history, copied, paths) == expected
    assert len(root_history.versions) == 1 and len(copied.versions) == 2 and sorted(paths) == [
        "p/a/freeze.json", "p/b/freeze.json", "p/side.txt"]
    # The documented remedy for a captured campaign: the owner's invalidation.md and a superseding campaign.
    world = frozen_world(tmp_path / "world")
    git_world(world)
    synthetic_candidate(world)
    commit_all(world, "synthetic capture")
    (frozen_dir(world) / "invalidation.md").write_bytes(
        b"# Invalidation: pilot-99\nReviewer: Test Owner (synthetic)\nDate: 2026-10-05\nScope: campaign\n"
        b"Reason: synthetic reason for a new campaign\n")
    code, out = run(world, "freeze", "--campaign", "pilot-100", "--write", "--frozen-at", FROZEN_AT,
                    "--supersede-reason", "synthetic supersede")
    assert code == 0, out
    world.reload_manifest()
    commit_all(world, "synthetic invalidation and pilot-100")
    code, out = run(world, "check-frozen")
    assert code == 0, out


# --------------------------------------------------------------------------------------------
# Round 5: frozen files in check, unreadable files, missing frozen files (synthetic data only)


HIGH_DEFECT = ["## Defect demo-d01", "Wording: A high synthetic defect.", "Severity: high", "Anchors: lib/model.py:5",
               "Counter-evidence: none (synthetic)", "Reason: synthetic", ""]


def test_check_never_tells_the_owner_to_edit_a_frozen_file_for_its_proposal_lines(tmp_path: Path, verified) -> None:
    """A frozen primary whose ">" proposal line was edited before the freeze is noted with the ledger text the
    freeze took, never with advice to restore lines in the frozen file (OWNERUX5-1)."""
    world = make_world(tmp_path)
    complete_world(world)
    claim = "> Claim: The synthetic model width comes from lib/model.py constants."
    path = world.root / wd.DECISIONS_REL / "pilot-demo.md"
    path.write_bytes(path.read_bytes().replace(claim.encode(), b"> Claim: an edited proposal line (synthetic)."))
    assert run(world, "freeze", "--campaign", "pilot-99", "--write", "--frozen-at", FROZEN_AT)[0] == 0
    world.reload_manifest()
    git_world(world)
    code, out = run(world, "check", "pilot-demo")
    assert code == 0 and "pilot-demo: 0 error(s), 0 to do; frozen in pilot-99." in out, out
    assert "the freeze of pilot-99 took the ledger's proposal: \"Claim: The synthetic model width comes from " \
           "lib/model.py constants.\". Leave this frozen file exactly as committed." in out, out
    assert "restore the lines the tool wrote" not in out and "template --show" not in out, out
    assert run(world, "check-frozen")[0] == 0


@pytest.mark.parametrize("second", ["frozen", "none", "added-after"])
def test_a_frozen_high_severity_defect_is_never_resolved_in_its_frozen_file(tmp_path: Path, verified,
                                                                             second: str) -> None:
    """After the freeze, the high-severity NOTE of a frozen primary says the defect was not second-reviewed in
    that campaign; with a second review added after the freeze it is a note for a new campaign. Neither asks
    anyone to add or resolve anything in the frozen file (OWNERUX5-1)."""
    world = make_world(tmp_path)
    complete_world(world)
    if second == "frozen":
        review = decide(fill_header(wd.task_template(world, "pilot-demo", second=True), SECOND), "Fact demo-f02",
                        "accept")
        write(world, "pilot-demo.second.md", complete(review))
    write(world, "pilot-demo.md", complete(insert_before(accept_all(world, "pilot-demo"), "## Disagreements",
                                                         HIGH_DEFECT)))
    assert run(world, "freeze", "--campaign", "pilot-99", "--write", "--frozen-at", FROZEN_AT)[0] == 0
    world.reload_manifest()
    git_world(world)
    if second == "added-after":
        review = decide(fill_header(wd.task_template(world, "pilot-demo", second=True), SECOND), "Fact demo-f02",
                        "accept")
        write(world, "pilot-demo.second.md", complete(review))
    _code, out = run(world, "check", "pilot-demo")
    notes = [line for line in out.splitlines() if "Defect demo-d01:" in line]
    assert len(notes) == 1 and notes[0].startswith(
        "evals/workflow/decisions/pilot-demo.md:"), out
    assert "pilot-demo: 0 error(s), 0 to do; frozen in pilot-99." in out, out
    if second == "added-after":
        assert "NOTE  Defect demo-d01: for a new campaign (evals/workflow/decisions/pilot-demo.second.md was added " \
               "after the freeze of pilot-99): the second review does not cover your own additions" in notes[0], notes
    else:
        assert "NOTE  Defect demo-d01: this high-severity defect was not second-reviewed in pilot-99 (a second review " \
               "covers your own additions only through its own additions); a second opinion needs a new campaign (" \
               in notes[0], notes
        assert "you resolve it" not in out and "adds it as" not in out and "recommended" not in notes[0], out


@pytest.mark.parametrize("damage", ["cp1252", "utf16", "title"])
def test_an_unreadable_frozen_second_review_keeps_the_primary_frozen_in_check(tmp_path: Path, verified,
                                                                              damage: str) -> None:
    """A frozen second review re-saved in another encoding, or with a damaged title, counts as changed after
    the freeze: the primary stays "frozen in" its campaign, its Disagreements line becomes a note for a new
    campaign, and the second-review file names its restore (OWNERUX5-2)."""
    world = second_review_world(tmp_path)
    rel = "evals/workflow/decisions/pilot-demo.second.md"
    path = world.root / rel
    raw = path.read_bytes()
    if damage == "cp1252":
        path.write_bytes(raw.replace(b"Reason: synthetic\n", b"Reason: synthetic \x96 re-saved\n", 1))
    elif damage == "utf16":
        path.write_bytes(raw.decode("utf-8").encode("utf-16"))
    else:
        path.write_bytes(raw.replace(b"# Second review: pilot-demo", b"# Second reviw pilot-demo", 1))
    code, out = run(world, "check", "pilot-demo")
    assert "pilot-demo: 0 error(s), 0 to do; frozen in pilot-99." in out, out
    assert "ERROR Disagreements" not in out, out
    assert f"NOTE  Disagreements: for a new campaign ({rel} changed after the freeze of pilot-99 and cannot be " \
           "read): " in out, out
    assert f"this file was frozen in pilot-99" in out and f"(git checkout -- {rel})" in out, out
    code, out = run(world, "check-frozen")
    assert code == 1 and f"Next: restore the frozen {rel} (git checkout -- {rel})" in out, out
    git(world.root, "checkout", "--", rel)
    assert run(world, "check-frozen")[0] == 0


@pytest.mark.parametrize("damage", ["cp1252", "utf16", "title"])
def test_freeze_and_check_frozen_report_an_unreadable_primary_without_a_traceback(tmp_path: Path, verified,
                                                                                  damage: str) -> None:
    """A primary decision file that cannot be parsed (a Windows ANSI save, a UTF-16 redirect of template --show,
    a damaged title) is a precondition of the freeze and a restore step of check-frozen (OWNERUX5-3)."""
    def spoil(path: Path) -> None:
        raw = path.read_bytes()
        if damage == "cp1252":
            path.write_bytes(raw.replace(b"> Claim:", b"> Claim \x96", 1))
        elif damage == "utf16":
            path.write_bytes(raw.decode("utf-8").encode("utf-16"))
        else:
            path.write_bytes(raw.replace(b"# Reference decisions: pilot-demo", b"# Reference decisons pilot-demo", 1))

    world = make_world(tmp_path)
    complete_world(world)
    rel = "evals/workflow/decisions/pilot-demo.md"
    path = world.root / rel
    original = path.read_bytes()
    spoil(path)
    code, out = run(world, "freeze", "--campaign", "pilot-99")
    assert code == 1 and f"{rel}: 1 error(s); it cannot be read as a reference-decisions file" in out, out
    path.write_bytes(original)
    assert run(world, "freeze", "--campaign", "pilot-99", "--write", "--frozen-at", FROZEN_AT)[0] == 0
    world.reload_manifest()
    git_world(world)
    spoil(path)
    code, out = run(world, "check-frozen")
    assert code == 1 and f"Next: restore the frozen {rel} (git checkout -- {rel}) to keep pilot-99" in out, out
    git(world.root, "checkout", "--", rel)
    assert run(world, "check-frozen")[0] == 0


def test_a_deleted_frozen_file_gets_the_restore_in_check(tmp_path: Path, verified,
                                                         capsys: pytest.CaptureFixture[str]) -> None:
    """check names the restore of a frozen decision file that is missing, never a new pending template, and
    check without a target reports it (OWNERUX5-4)."""
    world = make_world(tmp_path)
    complete_world(world)
    assert run(world, "freeze", "--campaign", "pilot-99", "--write", "--frozen-at", FROZEN_AT)[0] == 0
    world.reload_manifest()
    git_world(world)
    rel = "evals/workflow/decisions/pilot-demo.md"
    (world.root / rel).unlink()
    code, _out = run(world, "check", "pilot-demo")
    err = capsys.readouterr().err
    assert code == 2 and f"{rel} was frozen in pilot-99 and is missing; restore it (git checkout -- {rel}) to keep " \
                         "pilot-99, or freeze a new campaign" in err, err
    assert "template pilot-demo" not in err, err
    code, out = run(world, "check")
    assert code == 1 and f"{rel}:1: ERROR header: {rel} was frozen in pilot-99 and is missing; restore it " \
                         f"(git checkout -- {rel})" in out, out
    assert "pilot-demo.md: 1 error(s), 0 to do; missing (frozen in pilot-99)." in out, out
    git(world.root, "checkout", "--", rel)
    assert run(world, "check")[0] == 0


def test_an_unbound_renderer_of_an_invalidated_superseded_campaign_is_a_note(tmp_path: Path, verified) -> None:
    """A summary naming a tools/workflow_pilot.py that was never committed in its history fails check-frozen,
    and the owner's invalidation.md plus a superseding campaign turn that into a note, as the documented
    remedy says (INTEGRITY5-1, SPECDOCS5-1)."""
    world = frozen_world(tmp_path)
    git_world(world)
    synthetic_candidate(world)
    commit_all(world, "synthetic capture")
    (world.root / "tools").mkdir()
    (world.root / "tools/workflow_pilot.py").write_bytes(b"# a synthetic tools/workflow_pilot.py\n")
    synthetic_summary(world, "stop")
    summary = frozen_dir(world) / "stage1-summary.json"
    value = json.loads(summary.read_text(encoding="utf-8"))
    value["tooling"] = {"tools/workflow_pilot.py": "0" * 64}
    summary.write_bytes(er.canonical_json(value))
    commit_all(world, "synthetic stop naming a tool that was never committed")
    message = ("pilot-99/stage1-summary.json names a tools/workflow_pilot.py (sha256 000000000000...) that is neither "
               "the running one nor any version committed in the history of ")
    code, out = run(world, "check-frozen")
    assert code == 1 and message in out, out
    (frozen_dir(world) / "invalidation.md").write_bytes(
        b"# Invalidation: pilot-99\nReviewer: Test Owner (synthetic)\nDate: 2026-10-05\nScope: campaign\n"
        b"Reason: synthetic reason for a new campaign\n")
    code, out = run(world, "freeze", "--campaign", "pilot-100", "--write", "--frozen-at", FROZEN_AT,
                    "--supersede-reason", "synthetic supersede")
    assert code == 0, out
    world.reload_manifest()
    commit_all(world, "synthetic invalidation and pilot-100")
    code, out = run(world, "check-frozen")
    assert code == 0 and "check-frozen: pilot-99 (invalidated): evals/workflow/pilot/" + message in out, out


# --------------------------------------------------------------------------------------------
# Final round: honest-path fixes (synthetic data only)


@pytest.mark.parametrize("damage", ["utf16", "primary-title"])
def test_an_unreadable_second_review_never_asks_to_delete_the_resolutions(tmp_path: Path, verified,
                                                                          damage: str) -> None:
    """Before the freeze, a second review that exists but cannot be used (re-saved as UTF-16, or started from
    a copy of the primary) leaves the owner's resolution lines alone: the error names the unreadable file,
    never "there is no second review ... delete this line" (OWNERUX-F1)."""
    world = make_world(tmp_path)
    rel = "evals/workflow/decisions/pilot-demo.second.md"
    second = complete(decide(fill_header(wd.task_template(world, "pilot-demo", second=True), SECOND), "Fact demo-f02",
                             "reject", "Reason: synthetic"))
    path = write(world, "pilot-demo.second.md", second)
    write(world, "pilot-demo.md", complete(accept_all(world, "pilot-demo")).replace(
        "## Disagreements\n", "## Disagreements\ndemo-f02: kept after discussion (synthetic)\n"))
    code, out = run(world, "check", "pilot-demo")
    assert code == 0 and "pilot-demo: 0 error(s), 0 to do; ready to freeze." in out, out
    if damage == "utf16":
        path.write_bytes(second.encode("utf-16"))
    else:
        path.write_bytes(wd.task_template(world, "pilot-demo").encode("utf-8"))
    code, out = run(world, "check", "pilot-demo")
    assert code == 1 and "delete this line" not in out, out
    assert f'ERROR Disagreements: "demo-f02": {rel} cannot be read (see its errors); fix or restore it before ' \
           "resolving disagreements. Keep this line." in out, out
    # A second review that really does not exist still asks for the stray line to go.
    path.unlink()
    code, out = run(world, "check", "pilot-demo")
    assert code == 1 and 'there is no second review (pilot-demo.second.md) to disagree with; delete this line.' in out


@pytest.mark.parametrize("target, damage", [("pilot-demo", "utf16"), ("pilot-demo", "title"), ("run-policy", "utf16"),
                                            ("run-policy", "title")])
def test_check_names_the_restore_of_a_frozen_file_that_no_longer_parses(tmp_path: Path, verified, target: str,
                                                                        damage: str) -> None:
    """A frozen primary or run policy re-saved as UTF-16 or with a damaged title is reported with its frozen
    state and the restore, as for any other change after the freeze (OWNERUX-F2)."""
    world = make_world(tmp_path)
    complete_world(world)
    assert run(world, "freeze", "--campaign", "pilot-99", "--write", "--frozen-at", FROZEN_AT)[0] == 0
    world.reload_manifest()
    git_world(world)
    rel = f"evals/workflow/decisions/{target}.md"
    path = world.root / rel
    raw = path.read_bytes()
    path.write_bytes(raw.decode("utf-8").encode("utf-16") if damage == "utf16" else raw.replace(b"# ", b"#", 1))
    code, out = run(world, "check", target)
    assert code == 1 and "this file was frozen in pilot-99" in out and f"(git checkout -- {rel})" in out, out
    assert f"{target}.md: " in out and "0 to do; changed after the freeze of pilot-99." in out, out
    git(world.root, "checkout", "--", rel)
    code, out = run(world, "check", target)
    assert code == 0 and "frozen in pilot-99" in out, out


def test_a_frozen_dropped_anchor_note_asks_for_no_edit(tmp_path: Path, verified) -> None:
    """After the freeze, the dropped-anchor note of an unchanged frozen file says what the freeze recorded
    instead of asking to repeat the anchor (OWNERUX-F3)."""
    world = make_world(tmp_path)
    complete_world(world)
    primary = in_section(complete(accept_all(world, "pilot-demo")), "Fact demo-f03", "Decision: accept",
                         ["Decision: accept", "Anchors: train.py:20-22", "Reason: the config line adds nothing (synthetic)"])
    write(world, "pilot-demo.md", primary)
    code, out = run(world, "check", "pilot-demo")
    assert "repeat every proposed anchor you keep" in out, out
    assert run(world, "freeze", "--campaign", "pilot-99", "--write", "--frozen-at", FROZEN_AT)[0] == 0
    world.reload_manifest()
    git_world(world)
    code, out = run(world, "check", "pilot-demo")
    assert "frozen in pilot-99" in out and "repeat every proposed anchor" not in out, out
    assert "NOTE  Fact demo-f03: the freeze of pilot-99 recorded this fact without configs/a.py:2 (proposed); " \
           "changing its anchors needs a new campaign" in out, out


def test_template_never_replaces_a_deleted_frozen_file(tmp_path: Path, verified) -> None:
    """template refuses to write a pending template over a frozen decision file that was deleted, and names
    the restore instead (OWNERUX-F6)."""
    world = make_world(tmp_path)
    complete_world(world)
    assert run(world, "freeze", "--campaign", "pilot-99", "--write", "--frozen-at", FROZEN_AT)[0] == 0
    world.reload_manifest()
    git_world(world)
    rel = "evals/workflow/decisions/pilot-demo.md"
    (world.root / rel).unlink()
    code, out = run(world, "template", "pilot-demo")
    assert code == 1 and f"template: refusing; {rel} was frozen in pilot-99 and is missing; restore it (git checkout " \
                         f"-- {rel})" in out, out
    assert not (world.root / rel).exists()
    for name in ("pilot-demo.md", "pilot-book.md", "run-policy.md", "development-adjudication.md", "README.md"):
        (world.root / wd.DECISIONS_REL / name).unlink(missing_ok=True)
    code, out = run(world, "template", "--init-all")
    assert code == 1 and "template --init-all: refusing;" in out and "was frozen in pilot-99 and is missing" in out, out
    assert not (world.root / rel).exists()


def test_a_missing_git_is_named_as_the_reason_history_was_not_checked(tmp_path: Path, verified,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """Without git on PATH, the history note names the missing git instead of "not a Git work tree"
    (DISTCI-F5)."""
    world = frozen_world(tmp_path)
    git_world(world)
    empty = tmp_path / "no-git"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    history = wd.History(world)
    assert history.reason is not None and history.reason.startswith("git cannot run (cannot run git: ") and \
        history.reason.endswith("); install Git or put it on PATH"), history.reason
