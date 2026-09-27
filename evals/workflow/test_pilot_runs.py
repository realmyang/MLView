"""Tests for tools/workflow_pilot.py (plan, run-prepare, run-finish, review-template, check_file and
summarize) on a synthetic campaign.

Everything here is synthetic and lives in temporary directories: a two-repository corpus, a
synthetic MLView checkout with frozen files in the shape of the Campaign 2 specification (section
1.9), a stub pilot candidate (section 3.2) and runs whose artifacts are published by the real
helper. Operator facts and reviews are written by the tests as clearly labelled synthetic data
("Test Reviewer (synthetic)"). fetch_workflow_repos.verify_repo and the v2 workflow_candidate.check
are monkeypatched until streams D merges (section 8.3). These are tooling checks only: they are not
semantic accuracy, human review, a pilot run or live-host validation.
"""
from __future__ import annotations

import copy
import io
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import eval_records as er  # noqa: E402
import package_skill  # noqa: E402
import workflow_pilot as wp  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

EM = "—"
CAMPAIGN = "pilot-01"
HOSTS = ["codex", "claude-code"]
FROZEN_AT = "2026-10-01T00:00:00Z"
CAPTURED_AT = "2026-10-02T00:00:00Z"
STARTED = "2026-10-10T09:00:00Z"
ENDED = "2026-10-10T09:15:00Z"
NOW = "2026-10-20T00:00:00Z"
REVIEWER = "Test Reviewer (synthetic)"
CORPUS = {
    "demo-a": {"sparse": [], "files": {
        "train.py": "import data\nfor step in range(40):\n    data.update(step)\nsave()\n",
        "data.py": "def update(step):\n    return step\n",
        "README.md": "Synthetic demo A\n"}},
    "demo-b": {"sparse": ["src"], "files": {
        "src/train.py": "model = build()\nloss = model.fit()\nprint(loss)\n",
        "src/model.py": "def build():\n    return object()\n",
        "README.md": "Outside the sparse set; never copied into a workspace.\n"}},
}
TASKS = (("pilot-demo-a", "demo-a", "train.py"), ("pilot-demo-b", "demo-b", "src/train.py"))
SETTINGS = {host: {"model": f"synthetic-model-{host} (synthetic)", "reasoning": "synthetic-high",
                   "invocation": f"synthetic {host} invocation"} for host in HOSTS}
PATH_LEAK = wp.MACHINE_PATH_RE


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tools' own Git reads never see the developer's Git configuration (DISTCI4-2); a test that
    needs a configuration sets GIT_CONFIG_GLOBAL itself."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def sha(data: bytes) -> str:
    return er.sha256_bytes(data)


def git_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_AUTHOR_NAME": "Synthetic Test", "GIT_AUTHOR_EMAIL": "synthetic@example.invalid",
                "GIT_COMMITTER_NAME": "Synthetic Test", "GIT_COMMITTER_EMAIL": "synthetic@example.invalid",
                "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"})
    return env


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, env=git_env(), check=True)
    return result.stdout.decode("utf-8").strip()


def commit_files(repo: Path, files: dict[str, bytes], message: str = "synthetic") -> str:
    if not (repo / ".git").exists():
        repo.mkdir(parents=True, exist_ok=True)
        git(repo, "init", "--quiet")
    for rel, data in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def decision_bytes(task: str) -> bytes:
    return f"# Reference decisions: {task}\n> Synthetic decision file for tests; no human reviewed it.\n".encode()


def ledger_bytes(task: str) -> bytes:
    return f'{{"taskId": "{task}", "note": "synthetic ledger for tests"}}\n'.encode()


POLICY_SOURCE = b"# Pilot run policy\n> Synthetic run policy for tests; no human agreed to it.\n"


def reference(task: str, repo: str, commit: str, entry: str, *, extras: bool) -> dict:
    short = task.replace("pilot-", "")
    anchor = {"file": entry, "line": 1, "endLine": 1}
    facts = [{"id": f"{short}-f0{n}", "origin": "candidate", "decision": "accept",
              "claim": f"Synthetic fact {n} of {task}.", "candidateClaim": f"Synthetic fact {n} of {task}.",
              "basis": "observed", "essential": n < 3, "changed": [], "anchors": [{"id": f"{short}-a0{n}", **anchor}],
              "reason": None} for n in (1, 2, 3)]
    return {
        "format": "mlview-frozen-reference/1", "campaign": CAMPAIGN, "task": task, "repository": repo,
        "repositoryCommit": commit,
        "candidate": {"path": f"evals/workflow/reference-candidates/{task}.json", "sha256": sha(ledger_bytes(task))},
        "reviews": [{"role": "primary", "path": f"evals/workflow/decisions/{task}.md", "sha256": sha(decision_bytes(task)),
                     "reviewer": REVIEWER, "date": "2026-09-30", "transcribedBy": None}],
        "scenario": {"decision": "accept", "description": "Synthetic scenario.", "entrypoints": [entry], "arguments": [],
                     "reason": None},
        "facts": facts, "rejectedFacts": [], "essentialFactIds": [f"{short}-f01", f"{short}-f02"],
        "knownUnresolved": [
            {"id": f"{short}-u01", "origin": "candidate", "text": "A synthetic must-state unknown.", "runsMustState": True,
             "reason": None},
            {"id": f"{short}-u02", "origin": "candidate", "text": "A synthetic optional unknown.", "runsMustState": False,
             "reason": None}],
        "rejectedUnknowns": [], "nonDefects": [{"id": f"{short}-n01", "text": "A synthetic intentional behaviour."}],
        "rejectedNonDefects": [],
        "defects": [{"id": f"{short}-d01", "text": "A synthetic defect.", "severity": "medium", "anchors": [anchor]}] if extras else [],
        "disputes": [{"item": f"{short}-f01", "primary": "accept", "second": "reject",
                      "resolution": "Synthetic resolution."}] if extras else [],
        "sourceFiles": {entry: {"sha256": "0" * 64, "blob": "0" * 40}},
        "counts": {"facts": 3, "essential": 2, "runsMustState": 1, "nonDefects": 1, "defects": 1 if extras else 0},
    }


def make_policy(**changes) -> dict:
    policy = {
        "format": "mlview-run-policy/1", "campaign": CAMPAIGN,
        "source": {"path": "evals/workflow/decisions/run-policy.md", "sha256": sha(POLICY_SOURCE), "reviewer": REVIEWER,
                   "date": "2026-09-30"},
        "hosts": copy.deepcopy(SETTINGS),
        "environment": {"helperPython": "a synthetic Python 3.12 first on PATH"},
        "budget": {"activeMinutes": 20, "repairRounds": 2, "infrastructureRetries": 0},
        "scoring": {"qualifiedClaims": "not-supported", "perHostTargets": "no"},
        "conditions": {"baselineSessions": 4, "developmentAdjudicationBeforeStage1": "not-required"},
        "targets": {"structurallyValid": 1.0, "exactAnchors": 1.0, "supportedClaimPrecision": 0.95,
                    "essentialFactRecall": 0.85, "knownUnresolvedQualified": 1.0, "highSeverityFalseAccusations": 0},
        "privacy": {"publication": "Counts, statuses and hashes only (synthetic)."},
        "prompts": {"artifactPath": "pilot.mlview.json", "skillTemplateSha256": "0" * 64, "baselineTemplateSha256": "0" * 64},
    }
    for dotted, value in changes.items():
        section, key = dotted.split(".")
        policy[section][key] = value
    return policy


def task_prompt(task: str) -> str:
    return f"Explain the synthetic training loop of {task}."


def rendered_prompt(task: str, entry: str, condition: str) -> bytes:
    scenario = f"Description: Synthetic scenario.\nEntrypoints: {entry}\nArguments: none"
    tail = ("Inspect source without importing or executing target code. Publish one WorkflowDocument to "
            "pilot.mlview.json using the installed helper." if condition == "skill" else
            "Inspect source without importing or executing target code. Answer in this conversation.")
    return f"{task_prompt(task)}\n\nSelected scenario:\n{scenario}\n\n{tail}\n".encode("utf-8")


@dataclass
class World:
    base: Path
    root: Path
    corpus: Path
    pilot: Path

    def evidence(self, run_id: str) -> Path:
        return self.pilot / "evidence" / er.run_dir_name(run_id)

    def workspace(self, run_id: str) -> Path:
        return self.pilot / "workspaces" / er.run_dir_name(run_id)


def build_world(base: Path, *, policy: dict | None = None, candidate: dict | None = None) -> World:
    world = World(base, base / "mlview", base / "corpus", base / "pilot")
    commits = {name: commit_files(world.corpus / name, {rel: text.encode() for rel, text in spec["files"].items()})
               for name, spec in CORPUS.items()}
    files = {f"skills/mlview/{rel}": data for rel, data in package_skill.canonical_files(ROOT / "skills/mlview").items()}
    repositories = {"repos": [{"name": name, "url": f"https://example.invalid/{name}", "sha": commits[name],
                               "license": "MIT", "redistribute": False, "sparse": spec["sparse"]}
                              for name, spec in CORPUS.items()]}
    files[wp.REPOSITORIES_REL] = (json.dumps(repositories, indent=2) + "\n").encode()
    decision_files = {f"evals/workflow/decisions/{task}.md": decision_bytes(task) for task, _repo, _entry in TASKS}
    decision_files["evals/workflow/decisions/run-policy.md"] = POLICY_SOURCE
    ledgers = {f"evals/workflow/reference-candidates/{task}.json": ledger_bytes(task) for task, _repo, _entry in TASKS}
    files.update(decision_files)
    files.update(ledgers)
    campaign_rel = f"{wp.PILOT_REL}/{CAMPAIGN}"
    frozen: dict[str, bytes] = {}
    for task, repo, entry in TASKS:
        frozen[f"reference/{task}.json"] = er.canonical_json(reference(task, repo, commits[repo], entry, extras=repo == "demo-b"))
        for condition in ("skill", "baseline"):
            frozen[f"prompts/{condition}/{task}.txt"] = rendered_prompt(task, entry, condition)
    reference_set = {"format": "mlview-reference-set/1", "campaign": CAMPAIGN, "frozenAt": FROZEN_AT,
                     "tasks": [{"task": task, "path": f"reference/{task}.json", "sha256": sha(frozen[f"reference/{task}.json"]),
                                "essential": 2, "runsMustState": 1} for task, _repo, _entry in TASKS],
                     "totals": {"essential": 4, "runsMustState": 2},
                     "note": "Frozen from named human decisions; hashes identify bytes, not approval. (synthetic)"}
    frozen["reference-set.json"] = er.canonical_json(reference_set)
    frozen["policy.json"] = er.canonical_json(policy or make_policy())
    revision = "sha256:" + sha(frozen["reference-set.json"])
    tasks = {"version": 1, "hosts": HOSTS, "repetitions": 3,
             "pilotTargets": {"structurallyValid": 1.0, "exactAnchors": 1.0, "supportedClaimPrecision": 0.95,
                              "essentialFactRecall": 0.85, "knownUnresolvedQualified": 1.0,
                              "highSeverityFalseAccusations": 0},
             "tasks": [{"id": "dev-demo", "split": "development", "title": "Synthetic development task",
                        "repository": "MLView", "entrypoints": ["samples/demo/train.py"],
                        "prompt": "Synthetic development prompt.", "referenceStatus": "needs-human-review"}]
             + [{"id": task, "split": "heldout", "title": repo, "repository": repo, "url": f"https://example.invalid/{repo}",
                 "commit": commits[repo], "entrypoints": [entry], "prompt": task_prompt(task), "referenceStatus": "frozen"}
                for task, repo, entry in TASKS],
             "pilotFreeze": {"campaign": CAMPAIGN, "freeze": f"pilot/{CAMPAIGN}/freeze.json", "referenceRevision": revision}}
    files[wp.TASKS_REL] = (json.dumps(tasks, indent=2) + "\n").encode()
    for rel, data in frozen.items():
        files[f"{campaign_rel}/{rel}"] = data
    freeze = {"format": "mlview-freeze/1", "campaign": CAMPAIGN, "frozenAt": FROZEN_AT, "referenceRevision": revision,
              "supersedes": None, "files": {rel: sha(data) for rel, data in frozen.items()},
              "decisionFiles": {rel: sha(data) for rel, data in decision_files.items()},
              "candidateLedgers": {rel: sha(data) for rel, data in ledgers.items()},
              "tasksManifest": {"sha256": sha(files[wp.TASKS_REL]), "heldOut": {}},
              "repositories": {"sha256": sha(files[wp.REPOSITORIES_REL]),
                               "sparse": {name: spec["sparse"] for name, spec in CORPUS.items()}},
              "developmentAdjudication": None, "tooling": {}, "note": "Synthetic freeze for tests; it adds no approval."}
    files[f"{campaign_rel}/freeze.json"] = er.canonical_json(freeze)
    source = commit_files(world.root, files, "synthetic freeze")
    value = {"version": 2, "kind": "pilot-candidate", "campaign": CAMPAIGN, "pilotApproved": False,
             "source": {"commit": source, "tree": git(world.root, "rev-parse", "HEAD^{tree}"), "clean": True,
                        "capturedAt": CAPTURED_AT},
             "skill": package_skill.bundle_identity(package_skill.canonical_files(ROOT / "skills/mlview")),
             "components": [{"path": rel, "sha256": sha(files[rel]), "bytes": len(files[rel])}
                            for rel in (wp.TASKS_REL, wp.REPOSITORIES_REL, f"{campaign_rel}/freeze.json")],
             "vsix": {"file": "mlview-0.3.0.vsix", "sha256": "0" * 64, "bytes": 0, "version": "0.3.0",
                      "builtByCapture": True, "entries": []},
             "referenceRevision": revision, "remainingGates": [], "note": "Synthetic candidate for tests (synthetic)."}
    value.update(candidate or {})
    commit_files(world.root, {f"{campaign_rel}/candidate.json": er.canonical_json(value)}, "synthetic candidate")
    world.pilot.mkdir()
    return world


def patches(monkeypatch: pytest.MonkeyPatch, world: World) -> None:
    monkeypatch.setattr(wp.fetch_workflow_repos, "verify_repo",
                        lambda repo, corpus_root: {"name": repo["name"], "ok": True}, raising=False)
    monkeypatch.setattr(wp.workflow_candidate, "check", lambda record, root, vsix=None: [])
    monkeypatch.setattr(wp, "_now", lambda: NOW)
    monkeypatch.setenv("MLVIEW_PUBLIC_CORPUS_DIR", str(world.corpus))
    monkeypatch.delenv("MLVIEW_PILOT_DIR", raising=False)


def run_main(world: World, *args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = wp.main(list(args), root=world.root)
    return code, out.getvalue(), err.getvalue()


def pilot_args(world: World) -> list[str]:
    return ["--campaign", CAMPAIGN, "--pilot-dir", str(world.pilot)]


def draft_for(task: str, host: str) -> dict:
    repo, entry = next((r, e) for t, r, e in TASKS if t == task)
    lines = CORPUS[repo]["files"][entry].split("\n")
    return {
        "workflowVersion": "1.0", "title": f"Synthetic {task} workflow",
        "producer": {"kind": "host-llm", "host": host, "model": "synthetic-model"}, "revision": {"id": "rev-1"},
        "request": {"question": "Explain the synthetic training loop.", "scope": "Selected entrypoint (synthetic).",
                    "entrypoints": [entry], "configuration": "Source defaults; no overrides (synthetic)."},
        "phases": [{"id": "train", "label": "Training"}],
        "nodes": [{"id": "load", "label": "Load data", "phase": "train", "basis": "observed", "evidence": ["ev-1"],
                   "detail": "Synthetic node."},
                  {"id": "step", "label": "Update step", "phase": "train", "basis": "inferred", "evidence": ["ev-2"]}],
        "edges": [{"id": "e1", "source": "load", "target": "step", "label": "feeds", "basis": "observed",
                   "evidence": ["ev-1"]}],
        "findings": [{"id": "f1", "title": "Synthetic finding", "message": "A synthetic high-severity finding.",
                      "severity": "high", "nodeIds": ["step"], "basis": "observed", "evidence": ["ev-2"]}],
        "evidence": [{"id": "ev-1", "file": entry, "line": 1, "endLine": 1, "quote": lines[0]},
                     {"id": "ev-2", "file": entry, "line": 2, "endLine": 3, "quote": "\n".join(lines[1:3])}],
        "coverage": {"status": "scoped", "summary": "Synthetic entrypoint inspected.", "inspectedFiles": [entry],
                     "limitations": ["Synthetic limitation."]},
    }


def publish(workspace: Path, host: str, task: str, draft: dict | None = None) -> None:
    destination = wp._skill_destination(host)
    (workspace / "draft.draft.json").write_text(json.dumps(draft or draft_for(task, host)), encoding="utf-8")
    result = subprocess.run([sys.executable, str(workspace / destination / "scripts" / "artifact.py"), "publish",
                             "draft.draft.json", "--workspace", str(workspace), "--output", "pilot.mlview.json"],
                            capture_output=True, text=True, check=False)
    assert json.loads(result.stdout)["ok"] is True, result.stdout


def session_text(run_id: str, **changes: str) -> str:
    baseline = ":baseline:" in run_id
    host = run_id.split(":")[1]
    values = {"Status": "completed", "Failure": "", "Prompt sent": "", "Started": STARTED, "Ended": ENDED, "Active minutes": "15",
              "Approval wait minutes": "0.5", "Repair rounds": "" if baseline else "1",
              "Host version": "synthetic-host 1.0 (synthetic)", "Extension version": "0.3.0",
              "Model": SETTINGS[host]["model"], "Reasoning": SETTINGS[host]["reasoning"], "Resolved model": "unknown",
              "Invocation": "none (plain prompt; no skill) (synthetic)" if baseline else SETTINGS[host]["invocation"],
              "Helper Python": "" if baseline else "3.12.4",
              "Usage": "unknown", "Transcript": "transcript.txt", "UI log": "" if baseline else "ui-log.md",
              "Prior attempts": "0", "MLView available to host": "no" if baseline else "yes"}
    deviations = changes.pop("deviations", "")
    values.update(changes)
    return "\n".join([f"# Session: {run_id}"] + [f"{key}: {value}" for key, value in values.items()]
                     + ["## Deviations", deviations, ""])


def fill_review(path: Path, *, overrides: dict | None = None, drop: tuple = (), baseline_claims: tuple = (),
                reviewer: str = REVIEWER, complete: bool = True) -> None:
    """Replace every pending value like a (synthetic) human reviewer would."""
    overrides = overrides or {}
    baseline = ":baseline:" in path.read_text(encoding="utf-8").splitlines()[0]
    out, section = [], "header"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:]
            out.append(line)
            if section == "Claims" and baseline:
                out.extend(baseline_claims or ("response:1-2: supported",))
            continue
        if line == "Reviewer:":
            line = f"Reviewer: {reviewer}"
        elif line == "Date:":
            line = "Date: 2026-10-21"
        elif line == "Review: pending":
            line = "Review: complete" if complete else line
        elif line.endswith(": pending"):
            key = line[:-len(": pending")]
            if (section, key) in drop:
                continue
            default = {"Claims": "supported", "Severity": "agree",
                       "Essential facts": "covered response:1-2" if baseline else "covered node:load",
                       "Known unresolved": "stated response:3" if baseline else "stated coverage",
                       "Usability": "useful" if key == "task" else "clear", "Reference defects": "missed"}[section]
            line = f"{key}: {overrides.get((section, key), default)}"
        out.append(line)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def do_run(world: World, run_id: str, *, session: dict | None = None, publish_artifact: bool = True,
           draft: dict | None = None, before_finish=None, review: bool = True, review_kwargs: dict | None = None,
           transcript: str | None = None) -> None:
    code, out, err = run_main(world, "run-prepare", run_id, *pilot_args(world))
    assert code == 0, err
    task, host = run_id.split(":")[:2]
    baseline = ":baseline:" in run_id
    workspace, evidence = world.workspace(run_id), world.evidence(run_id)
    if not baseline and publish_artifact:
        publish(workspace, host, task, draft)
    if before_finish is not None:
        before_finish(workspace, evidence)
    prompt = (evidence / "PROMPT.txt").read_text(encoding="utf-8")
    answer = "The loop runs 40 steps.\nIt updates data.\nThe data origin is unknown.\n"
    (evidence / "transcript.txt").write_text(transcript if transcript is not None else prompt + "\n" + answer,
                                             encoding="utf-8")
    if not baseline:
        (evidence / "ui-log.md").write_text("Synthetic UI checklist: opened, filtered, navigated.\n", encoding="utf-8")
    (evidence / "session.md").write_text(session_text(run_id, **(session or {})), encoding="utf-8")
    code, out, err = run_main(world, "run-finish", run_id, *pilot_args(world))
    assert code == 0, out + err
    status = (session or {}).get("Status", "completed")
    if status == "completed" and review:
        code, out, err = run_main(world, "review-template", run_id, *pilot_args(world))
        assert code == 0, err
        fill_review(evidence / "review.md", **(review_kwargs or {}))


def stage1_ids(baselines: bool = True) -> list[str]:
    ids = [f"{task}:{host}:1" for task, _repo, _entry in TASKS for host in HOSTS]
    if baselines:
        ids += [f"{task}:{host}:baseline:1" for task, _repo, _entry in TASKS for host in HOSTS]
    return ids


@pytest.fixture(scope="module")
def base_world(tmp_path_factory) -> World:
    patcher = pytest.MonkeyPatch()
    try:
        world = build_world(tmp_path_factory.mktemp("pilot-base"))
        patches(patcher, world)
        for run_id in stage1_ids():
            do_run(world, run_id)
        yield world
    finally:
        patcher.undo()


@pytest.fixture
def world(base_world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    target = tmp_path / "w"
    shutil.copytree(base_world.base, target, symlinks=True)
    copied = World(target, target / "mlview", target / "corpus", target / "pilot")
    patches(monkeypatch, copied)
    return copied


@pytest.fixture
def fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    world = build_world(tmp_path / "fresh")
    patches(monkeypatch, world)
    return world


def summarize(world: World, stage: str = "1") -> dict:
    return wp.summarize(world.root, CAMPAIGN, stage, str(world.pilot))


def forget(world: World, run_id: str) -> None:
    """Fixture setup only: remove a run's evidence and its preparations.jsonl lines, as if it never ran."""
    shutil.rmtree(world.evidence(run_id))
    ledger = world.pilot / wp.LEDGER_FILE
    lines = [line for line in ledger.read_text(encoding="utf-8").splitlines(keepends=True)
             if json.loads(line)["run"] != run_id]
    ledger.write_text("".join(lines), encoding="utf-8")


def redo(world: World, run_id: str, **kwargs) -> None:
    forget(world, run_id)
    do_run(world, run_id, **kwargs)


def run_of(summary: dict, run_id: str) -> dict:
    return next(run for run in summary["runs"] if run["id"] == run_id)


def target(summary: dict, key: str) -> dict:
    return next(item for item in summary["targets"] if item["key"] == key)


def edit_json(path: Path, change) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    change(value)
    path.write_bytes(er.canonical_json(value))


def integrity_problems(world: World, stage: str = "1") -> list[str]:
    with pytest.raises(wp.IntegrityError) as caught:
        summarize(world, stage)
    return caught.value.problems


# --------------------------------------------------------------------------------------------
# plan


def test_plan_counts_and_exclusive_output(fresh: World, tmp_path: Path) -> None:
    code, out, _err = run_main(fresh, "plan")
    plan = json.loads(out)
    assert code == 0 and plan["frozen"] is False and plan["counts"] == {"skill": 12, "baseline": 0}
    assert plan["runs"][0] == {"id": "pilot-demo-a:codex:1", "task": "pilot-demo-a", "host": "codex", "repeat": 1,
                               "stage": 1, "condition": "skill", "repository": "demo-a",
                               "repositoryCommit": plan["runs"][0]["repositoryCommit"], "directory": "pilot-demo-a.codex.1"}
    code, out, _err = run_main(fresh, "plan", "--campaign", CAMPAIGN, "--stage", "1")
    plan = json.loads(out)
    assert plan["frozen"] is True and plan["counts"] == {"skill": 4, "baseline": 4}
    assert [run["id"] for run in plan["runs"]] == stage1_ids()
    code, out, _err = run_main(fresh, "plan", "--campaign", CAMPAIGN, "--stage", "2")
    assert json.loads(out)["counts"] == {"skill": 8, "baseline": 0}
    output = tmp_path / "plan.json"
    code, out, _err = run_main(fresh, "plan", "--campaign", CAMPAIGN, "--output", str(output))
    assert code == 0 and output.read_text(encoding="utf-8") == out
    code, _out, err = run_main(fresh, "plan", "--campaign", CAMPAIGN, "--output", str(output))
    assert code == 1 and "already exists; it is never overwritten" in err


def test_plan_without_baselines_when_the_policy_plans_none(tmp_path: Path, monkeypatch) -> None:
    world = build_world(tmp_path / "nobase", policy=make_policy(**{"conditions.baselineSessions": 0}))
    patches(monkeypatch, world)
    code, out, _err = run_main(world, "plan", "--campaign", CAMPAIGN, "--stage", "all")
    assert code == 0 and json.loads(out)["counts"] == {"skill": 12, "baseline": 0}


def test_real_manifest_plan_through_the_dispatcher() -> None:
    spec = __import__("importlib.util").util.spec_from_file_location("workflow_eval_for_pilot", TOOLS / "workflow_eval.py")
    module = __import__("importlib.util").util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out = io.StringIO()
    with redirect_stdout(out):
        assert module.main(["plan", "--stage", "1"]) == 0
    plan = json.loads(out.getvalue())
    assert plan["counts"] == {"skill": 24, "baseline": 0}
    with redirect_stdout(io.StringIO()) as all_out:
        assert module.main(["plan"]) == 0
    assert json.loads(all_out.getvalue())["counts"]["skill"] == 72


# --------------------------------------------------------------------------------------------
# run-prepare


def test_run_prepare_builds_an_isolated_workspace(fresh: World) -> None:
    code, out, err = run_main(fresh, "run-prepare", "pilot-demo-b:claude-code:1", *pilot_args(fresh))
    assert code == 0, err
    workspace, evidence = fresh.workspace("pilot-demo-b:claude-code:1"), fresh.evidence("pilot-demo-b:claude-code:1")
    files = sorted(p.relative_to(workspace).as_posix() for p in workspace.rglob("*") if p.is_file())
    assert "README.md" not in files and "src/train.py" in files and "src/model.py" in files
    assert all(not f.startswith(".agents/") for f in files)
    skill = package_skill.bundle_identity(package_skill.canonical_files(workspace / ".claude/skills/mlview"))
    assert skill == package_skill.bundle_identity(package_skill.canonical_files(ROOT / "skills/mlview"))
    assert not (workspace / ".git").exists()
    prompt = (fresh.root / wp.PILOT_REL / CAMPAIGN / "prompts/skill/pilot-demo-b.txt").read_bytes()
    assert (evidence / "PROMPT.txt").read_bytes() == prompt
    before = json.loads((evidence / "workspace-before.json").read_text(encoding="utf-8"))
    assert before["src/train.py"] == sha(CORPUS["demo-b"]["files"]["src/train.py"].encode())
    session = (evidence / "session.md").read_text(encoding="utf-8")
    assert session.startswith("# Session: pilot-demo-b:claude-code:1\n") and "Status: pending" in session
    assert "Operator checklist" in out and "synthetic-model-claude-code (synthetic)" in out
    assert wp.check_file(evidence / "session.md")[0].message.startswith("Status is still pending")
    # exclusive: a run is prepared once
    code, _out, err = run_main(fresh, "run-prepare", "pilot-demo-b:claude-code:1", *pilot_args(fresh))
    assert code == 1 and "was already prepared (1 attempt(s)" in err and "--retry" not in err
    assert "the run policy allows 0 infrastructure retries, so attempt 1 is kept and counted" in err


def test_run_prepare_baseline_has_no_skill(fresh: World) -> None:
    code, out, err = run_main(fresh, "run-prepare", "pilot-demo-a:codex:baseline:1", *pilot_args(fresh))
    assert code == 0, err
    workspace = fresh.workspace("pilot-demo-a:codex:baseline:1")
    assert not (workspace / ".agents").exists() and not (workspace / ".claude").exists()
    evidence = fresh.evidence("pilot-demo-a:codex:baseline:1")
    assert (evidence / "PROMPT.txt").read_bytes() == rendered_prompt("pilot-demo-a", "train.py", "baseline")
    assert "MLView available to host: no" in (evidence / "session.md").read_text(encoding="utf-8")
    assert "no MLView skill, plugin or artifact is available" in out


@pytest.mark.parametrize("where", ["claude-md", "agents-md", "git", "checkout"])
def test_run_prepare_refuses_a_pilot_directory_that_is_not_isolated(fresh: World, where: str) -> None:
    pilot = fresh.base / "outer" / "pilot"
    pilot.mkdir(parents=True)
    if where == "claude-md":
        (fresh.base / "outer" / "CLAUDE.md").write_text("instructions\n", encoding="utf-8")
    elif where == "agents-md":
        (pilot / "AGENTS.md").write_text("instructions\n", encoding="utf-8")
    elif where == "git":
        git(fresh.base / "outer", "init", "--quiet")
    else:
        pilot = fresh.root / "pilot-inside"
    code, _out, err = run_main(fresh, "run-prepare", "pilot-demo-a:codex:1", "--campaign", CAMPAIGN, "--pilot-dir", str(pilot))
    assert code == 1 and "not isolated" in err and wp.PILOT_DIR_REMEDY in err


def test_run_prepare_needs_a_pilot_directory(fresh: World) -> None:
    code, _out, err = run_main(fresh, "run-prepare", "pilot-demo-a:codex:1", "--campaign", CAMPAIGN)
    assert code == 1 and "MLVIEW_PILOT_DIR is not set" in err


def test_run_prepare_refusals(fresh: World, monkeypatch) -> None:
    code, _out, err = run_main(fresh, "run-prepare", "pilot-demo-a:codex:9", *pilot_args(fresh))
    assert code == 1 and "is not a planned run" in err
    monkeypatch.setattr(wp.fetch_workflow_repos, "verify_repo",
                        lambda repo, root: {"name": repo["name"], "ok": False, "blobMismatches": ["train.py"]}, raising=False)
    code, _out, err = run_main(fresh, "run-prepare", "pilot-demo-a:codex:1", *pilot_args(fresh))
    assert code == 1 and "failed verification (blobMismatches: train.py)" in err
    monkeypatch.setattr(wp.fetch_workflow_repos, "verify_repo", lambda repo, root: {"ok": True}, raising=False)


def test_run_prepare_installs_the_candidates_skill_whatever_the_checkout_holds(fresh: World) -> None:
    """A skill fix merged into main after the capture (ordinary development during a pilot) neither blocks
    run-prepare nor reaches the workspace: the candidate's skill is read from its source commit (HONEST-F1)."""
    candidate = package_skill.bundle_identity(package_skill.canonical_files(ROOT / "skills/mlview"))
    skill_md = fresh.root / "skills/mlview/SKILL.md"
    commit_files(fresh.root, {"skills/mlview/SKILL.md": skill_md.read_bytes() + b"\n<!-- a later fix (synthetic) -->\n",
                              "skills/mlview/scripts/added_later.py": b"# a file added after the capture (synthetic)\n"},
                 "synthetic skill fix merged after the capture")
    skill_md.write_text("an uncommitted edit (synthetic)\n", encoding="utf-8")
    for run_id in ("pilot-demo-a:codex:1", "pilot-demo-b:claude-code:1"):
        code, out, err = run_main(fresh, "run-prepare", run_id, *pilot_args(fresh))
        assert code == 0, err
        assert "Note: the skill in this checkout differs from the candidate's; the candidate's skill was installed " \
               "from its source commit" in out, out
        installed = fresh.workspace(run_id) / wp._skill_destination(run_id.split(":")[1])
        assert package_skill.bundle_identity(package_skill.canonical_files(installed)) == candidate
        assert not (installed / "scripts" / "added_later.py").exists()
        assert os.access(installed / "scripts" / "artifact.py", os.R_OK)
    code, out, err = run_main(fresh, "run-prepare", "pilot-demo-a:codex:baseline:1", *pilot_args(fresh))
    assert code == 0 and "differs from the candidate's" not in out, err
    # The sealed doctor.json compares the installed copy with the candidate's skill, not the checkout's.
    run_id = "pilot-demo-a:codex:1"
    publish(fresh.workspace(run_id), "codex", "pilot-demo-a")
    evidence = fresh.evidence(run_id)
    prompt = (evidence / "PROMPT.txt").read_text(encoding="utf-8")
    (evidence / "transcript.txt").write_text(prompt + "\nThe loop runs.\n", encoding="utf-8")
    (evidence / "ui-log.md").write_text("Synthetic UI checklist.\n", encoding="utf-8")
    (evidence / "session.md").write_text(session_text(run_id), encoding="utf-8")
    code, out, err = run_main(fresh, "run-finish", run_id, *pilot_args(fresh))
    assert code == 0, out + err
    doctor = json.loads((evidence / "doctor.json").read_text(encoding="utf-8"))
    assert doctor["canonicalIdentity"] == candidate and doctor["ok"] is True
    # From the candidate's source commit (which precedes candidate.json) the tools point to a branch instead.
    git(fresh.root, "checkout", "--quiet", "--", "skills/mlview/SKILL.md")
    git(fresh.root, "checkout", "--quiet", json.loads((fresh.root / wp.PILOT_REL / CAMPAIGN / "candidate.json")
                                                      .read_text(encoding="utf-8"))["source"]["commit"])
    code, _out, err = run_main(fresh, "run-prepare", "pilot-demo-b:codex:1", *pilot_args(fresh))
    assert code == 1 and "work on a branch that contains that commit" in err, err


def test_run_prepare_refuses_stage_2_without_a_committed_go(fresh: World) -> None:
    code, _out, err = run_main(fresh, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(fresh))
    assert code == 1 and "there is no committed stage1-summary.json" in err


def test_development_adjudication_gate(tmp_path: Path, monkeypatch) -> None:
    world = build_world(tmp_path / "gate",
                        policy=make_policy(**{"conditions.developmentAdjudicationBeforeStage1": "required"}))
    patches(monkeypatch, world)
    code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:codex:1", *pilot_args(world))
    assert code == 1 and "requires the development adjudication" in err and "is not committed" in err
    commit_files(world.root, {wp.ADJUDICATION_REL: b"# Development adjudication\n(synthetic placeholder)\n"},
                 "synthetic adjudication in progress")
    seen: list[bytes] = []

    class Result:  # the synthetic world has no development evidence, so the full checker is stubbed here
        def __init__(self, errors: int, todos: int) -> None:
            self.errors, self.todos, self.complete = errors, todos, not errors and not todos

    monkeypatch.setattr(wp, "_adjudication_check", lambda root, raw: seen.append(raw) or Result(0, 3))
    code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:codex:1", *pilot_args(world))
    assert code == 1 and "has 0 error(s) and 3 to do" in err and seen == [b"# Development adjudication\n(synthetic placeholder)\n"]
    monkeypatch.setattr(wp, "_adjudication_check", lambda root, raw: Result(0, 0))
    code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:codex:1", *pilot_args(world))
    assert code == 0, err


@pytest.mark.parametrize("variant", ["empty", "header-only", "typo"])
def test_the_adjudication_gate_uses_the_full_checker(monkeypatch, variant: str) -> None:
    import workflow_decisions as wd

    template = wd.adjudication_template(wd.World(ROOT, None))
    header = template.replace("Reviewer:\n", f"Reviewer: {REVIEWER}\n", 1).replace("Date:\n", "Date: 2026-09-30\n", 1)
    text = {"empty": "", "header-only": header.replace("Review: pending", "Review: complete"),
            "typo": header.replace(": pending", ": aprove", 1)}[variant]
    monkeypatch.setattr(wp, "_show_at_head", lambda root, rel: text.encode("utf-8"))
    reason = wp.adjudication_status(ROOT)
    assert reason is not None and "development-adjudication.md" in reason, reason
    if variant != "empty":
        assert ("to do" in reason) and (variant != "typo" or "0 error(s)" not in reason), reason


# --------------------------------------------------------------------------------------------
# run-finish, records and amendments


def test_sealed_record_shape_and_workspace_removal(world: World) -> None:
    evidence = world.evidence("pilot-demo-a:codex:1")
    record = json.loads((evidence / "record.json").read_text(encoding="utf-8"))
    assert (evidence / "record.json").read_bytes() == er.canonical_json(record)
    assert record["format"] == "mlview-pilot-run/1" and record["id"] == "pilot-demo-a:codex:1"
    assert record["stage"] == 1 and record["condition"] == "skill" and record["campaign"] == CAMPAIGN
    assert record["prompt"] == {"file": "PROMPT.txt", "sha256": sha((evidence / "PROMPT.txt").read_bytes()),
                                "frozen": "prompts/skill/pilot-demo-a.txt"}
    assert record["session"]["status"] == "completed" and record["session"]["activeMinutes"] == 15.0
    assert record["session"]["resolvedModel"] is None and record["session"]["mlviewAvailable"] is True
    assert record["workspace"]["removed"] is True and not world.workspace("pilot-demo-a:codex:1").exists()
    assert record["workspace"]["changedProjectFiles"] == [] and record["workspace"]["isolation"] == []
    assert record["evidence"]["artifact"]["file"] == "artifact.mlview.json"
    assert record["evidence"]["uiLog"]["file"] == "ui-log.md" and record["evidence"]["partialArtifact"] is None
    assert record["sealedAt"] == NOW and record["amendments"] == [] and list(record["tooling"]) == ["tools/workflow_pilot.py"]
    baseline = json.loads((world.evidence("pilot-demo-a:codex:baseline:1") / "record.json").read_text(encoding="utf-8"))
    assert baseline["condition"] == "baseline" and baseline["evidence"]["artifact"] is None
    assert baseline["evidence"]["uiLog"] is None and baseline["evidence"]["transcript"]["file"] == "transcript.txt"
    for path in world.pilot.rglob("*.json"):
        assert PATH_LEAK.search(path.read_text(encoding="utf-8")) is None, path


def test_run_finish_refuses_a_second_seal_and_an_unready_session(world: World, fresh: World) -> None:
    code, _out, err = run_main(world, "run-finish", "pilot-demo-a:codex:1", *pilot_args(world))
    assert code == 1 and "already sealed" in err and "--amend" in err
    code, _out, _err = run_main(fresh, "run-prepare", "pilot-demo-a:codex:1", *pilot_args(fresh))
    code, out, err = run_main(fresh, "run-finish", "pilot-demo-a:codex:1", *pilot_args(fresh))
    assert code == 1 and "session.md is not ready (0 error(s), 1 to do)" in err and "Status is still pending" in out
    evidence = fresh.evidence("pilot-demo-a:codex:1")
    (evidence / "session.md").write_text(session_text("pilot-demo-a:codex:1"), encoding="utf-8")
    code, out, err = run_main(fresh, "run-finish", "pilot-demo-a:codex:1", *pilot_args(fresh))
    assert code == 1 and "UI log: ui-log.md does not exist" in out and "(1 error(s), 0 to do)" in err
    (evidence / "ui-log.md").write_text("Synthetic UI checklist.\n", encoding="utf-8")
    code, out, err = run_main(fresh, "run-finish", "pilot-demo-a:codex:1", *pilot_args(fresh))
    assert code == 1 and "a completed skill run needs pilot.mlview.json at the workspace root" in err
    assert not (evidence / "record.json").exists() and fresh.workspace("pilot-demo-a:codex:1").is_dir()


def test_session_checker_messages(tmp_path: Path) -> None:
    evidence = tmp_path / "ev"
    evidence.mkdir()
    text = session_text("pilot-demo-a:codex:baseline:1", **{
        "Status": "failed", "Failure": "oops", "Started": "2026-10-10 09:00", "Active minutes": "ten",
        "Repair rounds": "x", "MLView available to host": "maybe", "Transcript": "../t.txt",
        "deviations": f"Host restarted at 10:05 {EM} invalidates: sometimes"})
    (evidence / "session.md").write_text(text, encoding="utf-8")
    messages = [f"{p.level} {p.section}: {p.message}" for p in wp.check_file(evidence / "session.md")]
    assert messages == [
        'ERROR header: "Failure: oops" does not start with a failure kind. Write one of: no-publication, repair-budget, '
        f'host-error, cancelled, setup, protocol, then " -- <detail>" (or " {EM} <detail>").',
        'ERROR header: Started "2026-10-10 09:00" is not an RFC 3339 time; write it like 2026-10-10T09:02:11Z.',
        'ERROR header: Active minutes "ten" is not a number of minutes (decimals allowed, like 16.5).',
        'ERROR header: Repair rounds "x" is not a whole number.',
        'ERROR header: Transcript: "../t.txt" must be a file name inside the evidence directory, other than the files the '
        "tool writes.",
        "ERROR header: MLView available to host must be yes or no.",
        f'ERROR Deviations: "Host restarted at 10:05 {EM} invalidates: sometimes" must end with " -- invalidates: yes" or '
        f'" -- invalidates: no" (" {EM} " also works).',
    ]
    for failure, hint in (("host-error - the host crashed", 'a single "-" is not a separator'),
                          ("host-error the host crashed", 'write the detail after " -- <detail>"')):
        (evidence / "session.md").write_text(session_text("pilot-demo-a:codex:baseline:1", Status="failed",
                                                          Failure=failure), encoding="utf-8")
        assert any(hint in p.message for p in wp.check_file(evidence / "session.md")), failure
    (evidence / "session.md").write_text(session_text("pilot-demo-a:codex:baseline:1", Status="failed",
                                                      Failure="host-error -- the host crashed (synthetic)"), encoding="utf-8")
    assert not [p for p in wp.check_file(evidence / "session.md") if "Failure" in p.message]
    (evidence / "session.md").write_text(session_text("pilot-demo-a:codex:1", **{
        "Resolved model": "synthetic model from D:/models/x (synthetic)",
        "deviations": f"copied the log from /home/someone/log {EM} invalidates: no"}), encoding="utf-8")
    leaks = [p.message for p in wp.check_file(evidence / "session.md") if "machine path" in p.message]
    assert len(leaks) == 2 and "Resolved model contains a machine path (D:/)" in leaks[1] + leaks[0]
    (evidence / "session.md").write_text(session_text("pilot-demo-a:codex:1", **{"MLView available to host": "no",
                                                                                   "Ended": "2026-10-10T08:00:00Z"}),
                                         encoding="utf-8")
    messages = [p.message for p in wp.check_file(evidence / "session.md")]
    assert "Ended is before Started." in messages
    assert 'a completed skill session must say "MLView available to host: yes".' in messages
    assert any(m.startswith("UI log: ui-log.md does not exist") for m in messages)


def test_failed_run_keeps_a_partial_artifact_and_is_never_scored(world: World) -> None:
    def half_publish(workspace: Path, _evidence: Path) -> None:
        (workspace / "pilot.mlview.json").write_text('{"partial": true}\n', encoding="utf-8")

    redo(world, "pilot-demo-a:codex:1", publish_artifact=False, before_finish=half_publish,
         session={"Status": "timed-out", "Failure": f"repair-budget {EM} validator kept failing", "Active minutes": "31"})
    record = json.loads((world.evidence("pilot-demo-a:codex:1") / "record.json").read_text(encoding="utf-8"))
    assert record["evidence"]["artifact"] is None and record["evidence"]["partialArtifact"]["file"] == "partial-artifact.mlview.json"
    assert record["session"]["failure"] == {"kind": "repair-budget", "detail": "validator kept failing"}
    code, _out, err = run_main(world, "review-template", "pilot-demo-a:codex:1", *pilot_args(world))
    assert code == 1 and "only completed runs are reviewed" in err
    summary = summarize(world)
    run = run_of(summary, "pilot-demo-a:codex:1")
    assert run["status"] == "timed-out" and run["SV"] == 0 and run["invalidReasons"] == []  # timed-out may exceed the budget
    assert summary["decision"]["value"] == "stop"
    assert summary["failures"]["runs"] == [{"id": "pilot-demo-a:codex:1", "status": "timed-out", "failure": "repair-budget",
                                            "detail": "validator kept failing", "invalidReasons": []}]


def test_completed_skill_run_needs_its_artifact(fresh: World) -> None:
    with pytest.raises(AssertionError, match="needs pilot.mlview.json at the workspace root"):
        do_run(fresh, "pilot-demo-a:codex:1", publish_artifact=False)


def test_amend_keeps_an_audit_trail(world: World) -> None:
    run_id = "pilot-demo-a:codex:1"
    evidence = world.evidence(run_id)
    previous = (evidence / "record.json").read_bytes()
    (evidence / "session.md").write_text(session_text(run_id, **{"Approval wait minutes": "2"}), encoding="utf-8")
    code, out, err = run_main(world, "run-finish", run_id, *pilot_args(world), "--amend", "Approval wait was misread")
    assert code == 0, err
    record = json.loads((evidence / "record.json").read_text(encoding="utf-8"))
    assert record["session"]["approvalWaitMinutes"] == 2.0 and record["sealedAt"] == NOW
    assert record["amendments"] == [{"at": NOW, "reason": "Approval wait was misread", "previous": sha(previous)}]
    assert (evidence / "record.previous-1.json").read_bytes() == previous
    summary = summarize(world)
    assert run_of(summary, run_id)["amendments"] == [{"at": NOW, "reason": "Approval wait was misread"}]
    assert next(r for r in summary["inputs"]["runs"] if r["id"] == run_id)["amendments"] == [sha(previous)]
    (evidence / "record.previous-1.json").write_text("{}", encoding="utf-8")
    assert any("amendments[0]" in p for p in integrity_problems(world))
    (evidence / "record.previous-1.json").write_bytes(previous)
    (evidence / "doctor.json").write_text("{}\n", encoding="utf-8")
    code, _out, err = run_main(world, "run-finish", run_id, *pilot_args(world), "--amend", "again")
    assert code == 1 and "machine-written evidence changed since sealing: doctor.json" in err
    code, _out, err = run_main(world, "run-finish", "pilot-demo-b:codex:1", *pilot_args(world), "--amend", " ")
    assert code == 1 and "--amend needs a reason" in err


def test_amend_to_timed_out_moves_the_artifact_out_of_scoring(world: World) -> None:
    run_id = "pilot-demo-b:codex:1"
    evidence = world.evidence(run_id)
    (evidence / "session.md").write_text(session_text(run_id, Status="timed-out", Failure="host-error",
                                                      **{"Active minutes": "25"}), encoding="utf-8")
    code, _out, err = run_main(world, "run-finish", run_id, *pilot_args(world), "--amend", "The session actually timed out")
    assert code == 0, err
    record = json.loads((evidence / "record.json").read_text(encoding="utf-8"))
    assert record["evidence"]["artifact"] is None and record["evidence"]["partialArtifact"]["file"] == "artifact.mlview.json"
    problems = summarize(world)
    run = run_of(problems, run_id)
    assert run["status"] == "timed-out" and run["reviewStatus"] == "problems"  # a review of a non-completed run is refused
    assert problems["decision"]["value"] == "incomplete"
    os.remove(evidence / "review.md")
    assert summarize(world)["decision"]["value"] == "stop"


# --------------------------------------------------------------------------------------------
# summarize: go, Markdown from JSON and exclusive recording


def test_go_summary_markdown_from_json_and_exclusive_record(world: World) -> None:
    summary = summarize(world)
    assert summary["decision"]["value"] == "go", summary["decision"]
    assert summary["decision"]["label"] == "computed against the predefined targets; not an approval"
    assert wp.GO_TEXT in summary["decision"]["reasons"] and summary["pilotApproved"] is False
    assert {t["key"]: (t["numerator"], t["denominator"], t["met"]) for t in summary["targets"]} == {
        "structurallyValid": (4, 4, True), "exactAnchors": (8, 8, True), "supportedClaimPrecision": (24, 24, True),
        "essentialFactRecall": (8, 8, True), "knownUnresolvedQualified": (4, 4, True),
        "highSeverityFalseAccusations": (0, 4, True)}
    run = run_of(summary, "pilot-demo-a:codex:1")
    assert run["claims"] == {"observed": {"supported": 5, "qualified": 0, "unsupported": 0},
                             "inferred": {"supported": 1, "qualified": 0, "unsupported": 0}, "noClaim": 0,
                             "unresolvedBasis": 0}
    assert (run["SV"], run["E"], run["X"], run["reviewer"], run["promptInTranscript"]) == (1, 2, 2, REVIEWER, "yes")
    assert summary["disputedEssentialFacts"] == [{"task": "pilot-demo-b", "item": "demo-b-f01"}]
    assert summary["caveats"][:6] == wp.caveats(2, 2, 3) and "Disputed essential facts: demo-b-f01." in summary["caveats"]
    assert summary["caveats"][0].startswith("The 4 Stage 1 runs are 2 pinned scenarios \u00d7 2 configured host workflows")
    assert summary["reported"]["severity"] == {"agree": 4, "too-high": 0, "too-low": 0}
    assert summary["reported"]["referenceDefects"] == {"found": 0, "missed": 2}
    assert summary["reported"]["usability"]["task"] == {"useful": 4}
    assert target(summary, "supportedClaimPrecision")["byBasis"] == {
        "inferred": {"numerator": 4, "denominator": 4, "value": 1.0},
        "observed": {"numerator": 20, "denominator": 20, "value": 1.0}}
    assert summary["verification"] == {"complete": True, "notes": []}
    assert summary["perHost"]["codex"]["essentialFactRecall"] == {"numerator": 4, "denominator": 4, "value": 1.0}
    assert set(summary["perTask"]) == {"pilot-demo-a", "pilot-demo-b"} and summary["macro"]["essentialFactRecall"] == 1.0
    assert summary["sensitivity"]["essentialFactRecall"] == {"min": 1.0, "minWithout": "pilot-demo-a", "max": 1.0,
                                                             "maxWithout": "pilot-demo-b"}
    baselines = summary["baselines"]
    assert (baselines["planned"], baselines["completed"], baselines["reviewed"]) == (4, 4, 4)
    assert baselines["recall"] == {"numerator": 8, "denominator": 8, "value": 1.0}
    assert baselines["precision"] == {"numerator": 4, "denominator": 4, "value": 1.0}
    assert baselines["paired"][0] == {"task": "pilot-demo-a", "host": "codex",
                                      "skill": {"status": "completed", "reviewed": True, "ess": 2, "ESS": 2, "unk": 1, "UNK": 1,
                                                "precision": {"numerator": 6, "denominator": 6, "value": 1.0}},
                                      "baseline": {"status": "completed", "reviewed": True, "ess": 2, "ESS": 2, "unk": 1,
                                                   "UNK": 1, "precision": {"numerator": 1, "denominator": 1, "value": 1.0}},
                                      "recallDifference": 0.0}
    code, markdown, err = run_main(world, "summarize", *pilot_args(world), "--stage", "1")
    assert code == 0 and markdown == wp.render_markdown(json.loads(er.canonical_json(summary)))
    assert markdown == wp.render_markdown(summary)  # key order does not change the rendering
    assert markdown.startswith(f"# MLView pilot {CAMPAIGN} {EM} Stage 1 summary (2026-10-20)\n**Decision: GO** {EM} "
                               "computed against the predefined targets; not an approval.")
    assert "| Structurally valid published artifacts | 4/4 | 100% | yes |" in markdown
    assert "| Supported claims (observed+inferred; qualified = not-supported) | 24/24 | >=95% | yes |" in markdown
    assert summary["openRetries"] == [] and "Retries still open" not in markdown
    code, out, err = run_main(world, "summarize", *pilot_args(world), "--stage", "1", "--json", "--record")
    assert code == 0, err
    recorded = world.root / wp.PILOT_REL / CAMPAIGN / "stage1-summary.json"
    assert recorded.read_text(encoding="utf-8") == out and json.loads(out) == summary
    regenerated = wp.render_markdown(json.loads(recorded.read_text(encoding="utf-8")))
    assert (recorded.with_suffix(".md")).read_text(encoding="utf-8") == regenerated
    assert PATH_LEAK.search(out) is None and PATH_LEAK.search(regenerated) is None
    code, _out, err = run_main(world, "summarize", *pilot_args(world), "--stage", "1", "--record")
    assert code == 1 and "already exists; recorded summaries are never overwritten" in err


def test_summarize_is_deterministic_and_ignores_finder_files(world: World) -> None:
    (world.pilot / "evidence" / ".DS_Store").write_bytes(b"\0")
    assert er.canonical_json(summarize(world)) == er.canonical_json(summarize(world))


# --------------------------------------------------------------------------------------------
# summarize: integrity errors (section 4.5 A-C)


def _tamper_record(field_path: tuple, value):
    def change(record):
        target_value = record
        for key in field_path[:-1]:
            target_value = target_value[key]
        target_value[field_path[-1]] = value
    return change


@pytest.mark.parametrize("name,mutate,expected", [
    ("fabricated path", lambda w, ev: edit_json(ev / "record.json", _tamper_record(("evidence", "transcript", "file"), "missing.txt")),
     "evidence.transcript: missing.txt does not exist"),
    ("hash mismatch", lambda w, ev: (ev / "transcript.txt").write_text("edited\n", encoding="utf-8"),
     "evidence.transcript: transcript.txt does not match its sealed SHA-256"),
    ("dot-dot path", lambda w, ev: edit_json(ev / "record.json", _tamper_record(("evidence", "uiLog", "file"), "../ui-log.md")),
     "evidence.uiLog: '../ui-log.md' must stay inside its root"),
    ("wrong prompt hash", lambda w, ev: ((ev / "PROMPT.txt").write_text("changed prompt\n", encoding="utf-8"),
                                         edit_json(ev / "record.json", _tamper_record(("prompt", "sha256"), sha(b"changed prompt\n")))),
     "prompt: sha256 differs from the freeze.json entry for prompts/skill/pilot-demo-a.txt"),
    ("wrong candidate", lambda w, ev: edit_json(ev / "record.json", _tamper_record(("candidateSha256",), "0" * 64)),
     "record.json candidateSha256: differs from sha256(candidate.json)"),
    ("wrong referenceRevision", lambda w, ev: edit_json(ev / "record.json", _tamper_record(("referenceRevision",), "sha256:" + "1" * 64)),
     "record.json referenceRevision: differs from the frozen referenceRevision"),
    ("edited artifact", lambda w, ev: (ev / "artifact.mlview.json").write_text("{}", encoding="utf-8"),
     "evidence.artifact: artifact.mlview.json does not match its sealed SHA-256"),
    ("edited session", lambda w, ev: (ev / "session.md").write_text(
        session_text("pilot-demo-a:codex:1", **{"Active minutes": "5"}), encoding="utf-8"),
     "session: session.md does not match its sealed SHA-256"),
    ("record session fields", lambda w, ev: edit_json(ev / "record.json", _tamper_record(("session", "activeMinutes"), 5.0)),
     "record.json session fields differ from session.md"),
    ("edited workspace snapshot", lambda w, ev: (ev / "workspace-after.json").write_text("{}\n", encoding="utf-8"),
     "workspace.after: workspace-after.json does not match its sealed SHA-256"),
])
def test_integrity_errors_abort_without_a_decision(world: World, name: str, mutate, expected: str) -> None:
    evidence = world.evidence("pilot-demo-a:codex:1")
    mutate(world, evidence)
    problems = integrity_problems(world)
    assert any(expected in problem for problem in problems), problems
    assert all(problem.startswith("pilot-demo-a:codex:1: ") for problem in problems)
    code, out, err = run_main(world, "summarize", *pilot_args(world), "--stage", "1")
    assert code == 1 and out == "" and "integrity problem(s); no decision was computed" in err


def test_symlinked_evidence_is_refused(world: World) -> None:
    evidence = world.evidence("pilot-demo-a:codex:1")
    real = world.base / "elsewhere.txt"
    shutil.move(str(evidence / "transcript.txt"), real)
    try:
        (evidence / "transcript.txt").symlink_to(real)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    assert any("transcript.txt passes through a symbolic link" in p for p in integrity_problems(world))


def test_unplanned_and_duplicate_run_ids(world: World) -> None:
    shutil.copytree(world.evidence("pilot-demo-a:codex:1"), world.pilot / "evidence" / "pilot-demo-a.codex.9")
    shutil.copytree(world.evidence("pilot-demo-a:codex:1"), world.pilot / "evidence" / "pilot-demo-a.codex.2")
    (world.pilot / "evidence" / "notes").mkdir()
    problems = integrity_problems(world)
    assert "evidence/pilot-demo-a.codex.9: pilot-demo-a:codex:9 is not a planned run of pilot-01" in problems
    assert "evidence/notes: not a pilot run directory name" in problems
    assert any("pilot-demo-a:codex:2: record.json claims the run ID pilot-demo-a:codex:1" in p and "duplicate ID" in p
               for p in problems)
    assert any("pilot-demo-a:codex:2: record.json id: 'pilot-demo-a:codex:1' differs from the plan" in p for p in problems)


def test_campaign_chain_errors(world: World, monkeypatch) -> None:
    candidate_path = world.root / wp.PILOT_REL / CAMPAIGN / "candidate.json"
    original = candidate_path.read_bytes()
    edit_json(candidate_path, lambda c: c.update(kind="development-snapshot"))
    assert any('need version 2, kind "pilot-candidate"' in p for p in integrity_problems(world))
    candidate_path.write_bytes(original)
    monkeypatch.setattr(wp.workflow_candidate, "check", lambda record, root, vsix=None: ["changed component: webview/dist/mlview.js",
                                                                                           "drift at HEAD: tasks.json"])
    assert integrity_problems(world) == ["candidate.json: changed component: webview/dist/mlview.js"]
    monkeypatch.setattr(wp.workflow_candidate, "check", lambda record, root, vsix=None: [])
    edit_json(candidate_path, lambda c: c["components"][0].update(sha256="0" * 64))
    assert "evals/workflow/tasks.json at " in integrity_problems(world)[0]
    candidate_path.write_bytes(original)
    frozen_policy = world.root / wp.PILOT_REL / CAMPAIGN / "policy.json"
    frozen_policy.write_text("{}", encoding="utf-8")
    git(world.root, "commit", "--quiet", "-am", "edit a frozen file after capture")
    assert summarize(world)["decision"]["value"] == "go"  # frozen inputs are read at the candidate commit
    edit_json(candidate_path, lambda c: c["source"].update(commit="f" * 40))
    assert "not in this repository" in integrity_problems(world)[0]


def test_shallow_clone_is_refused(world: World, tmp_path: Path) -> None:
    clone = tmp_path / "shallow"
    subprocess.run(["git", "clone", "--quiet", "--depth", "1", world.root.as_uri(), str(clone)], check=True,
                   capture_output=True, env=git_env())
    with pytest.raises(wp.IntegrityError) as caught:
        wp.summarize(clone, CAMPAIGN, "1", str(world.pilot))
    assert "shallow clone" in caught.value.problems[0]


# --------------------------------------------------------------------------------------------
# summarize: protocol invalidations (section 4.5 D)


def _edit_skill(workspace: Path, _evidence: Path) -> None:
    path = workspace / ".agents/skills/mlview/SKILL.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nLocal edit.\n", encoding="utf-8")


def _edit_project(workspace: Path, _evidence: Path) -> None:
    (workspace / "train.py").write_text("changed\n", encoding="utf-8")
    (workspace / "notes.txt").write_text("new file\n", encoding="utf-8")


def _install_into_baseline(workspace: Path, _evidence: Path) -> None:
    wp.install_skill.install(workspace, ".agents/skills/mlview")


@pytest.mark.parametrize("run_id,kwargs,reason", [
    ("pilot-demo-a:codex:1", {"session": {"Model": "another-model"}},
     'model "another-model" differs from the policy "synthetic-model-codex (synthetic)"'),
    ("pilot-demo-a:codex:1", {"session": {"Invocation": "Synthetic CODEX invocation "}}, None),
    ("pilot-demo-a:codex:1", {"session": {"Active minutes": "25"}}, "active minutes 25 exceed the budget of 20"),
    ("pilot-demo-a:codex:1", {"session": {"Repair rounds": "3"}}, "repair rounds 3 exceed the limit of 2"),
    ("pilot-demo-a:codex:1", {"session": {"Helper Python": "3.9.6"}}, "helper Python 3.9.6 is older than 3.10"),
    ("pilot-demo-a:codex:1", {"session": {"Started": "2026-09-30T00:00:00Z"}}, "started before the freeze"),
    ("pilot-demo-a:codex:1", {"session": {"deviations": f"Prompt sent twice {EM} invalidates: yes"}},
     "deviation: Prompt sent twice"),
    ("pilot-demo-a:codex:1", {"before_finish": _edit_project}, "2 project file(s) changed in the workspace (notes.txt, train.py)"),
    ("pilot-demo-a:codex:1", {"before_finish": _edit_skill}, "the installed skill differs from the candidate's skill identity"),
    ("pilot-demo-a:codex:1", {"draft": {**draft_for("pilot-demo-a", "codex"),
                                        "producer": {"kind": "host-llm", "host": "claude-code"}}},
     "artifact producer.host is 'claude-code', not codex"),
    ("pilot-demo-a:codex:baseline:1", {"before_finish": _install_into_baseline},
     "an MLView skill was installed in the baseline workspace"),
])
def test_protocol_violations_make_a_run_invalid(world: World, run_id: str, kwargs: dict, reason: str | None) -> None:
    redo(world, run_id, **kwargs)
    summary = summarize(world)
    run = next(r for r in summary["runs"] + [dict(p["baseline"], id=f"{p['task']}:{p['host']}:baseline:1")
                                             for p in summary["baselines"]["paired"]] if r["id"] == run_id)
    if reason is None:  # trimmed, case-insensitive comparison
        assert run["status"] == "completed" and summary["decision"]["value"] == "go"
        return
    assert run["status"] == "invalid"
    if ":baseline:" not in run_id:
        assert reason in run["invalidReasons"], run["invalidReasons"]
        assert run["SV"] == 0 and summary["decision"]["value"] == "stop"
        assert any(line.startswith(f"T1 structurallyValid: 3/4") for line in summary["decision"]["reasons"])
        assert "Runs counted invalid count as failures; the owner may record an invalidation." in summary["caveats"]
    else:
        assert summary["decision"]["value"] == "go"  # baselines never gate


def test_isolation_lost_after_prepare_invalidates_the_run(world: World) -> None:
    def add_instructions(_workspace: Path, _evidence: Path) -> None:
        (world.pilot / "CLAUDE.md").write_text("instructions\n", encoding="utf-8")

    redo(world, "pilot-demo-b:claude-code:1", before_finish=add_instructions)
    run = run_of(summarize(world), "pilot-demo-b:claude-code:1")
    assert run["invalidReasons"] == ["workspace isolation: CLAUDE.md in the pilot directory or a parent would be read by a "
                                     "host as instructions"]


def test_unknown_producer_host_is_a_warning(world: World) -> None:
    redo(world, "pilot-demo-a:codex:1", draft={**draft_for("pilot-demo-a", "codex"),
                                               "producer": {"kind": "host-llm", "host": "unknown"}})
    summary = summarize(world)
    run = run_of(summary, "pilot-demo-a:codex:1")
    assert run["status"] == "completed" and run["warnings"] == ["artifact producer.host is unknown"]
    assert summary["decision"]["value"] == "go"


def test_prompt_missing_from_the_transcript_is_a_warning(world: World) -> None:
    redo(world, "pilot-demo-a:codex:1", transcript="A transcript without the prompt.\n")
    run = run_of(summarize(world), "pilot-demo-a:codex:1")
    assert run["promptInTranscript"] == "no" and run["status"] == "completed"
    assert "the frozen prompt was not found in the transcript (after whitespace normalisation)" in run["warnings"]


# --------------------------------------------------------------------------------------------
# summarize: artifacts (section 4.5 E) and failures


def _publish_then(edit):
    def mutate(workspace: Path, _evidence: Path) -> None:
        path = workspace / "pilot.mlview.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        edit(value)
        path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return mutate


def test_invalid_artifact_scores_zero(world: World) -> None:
    redo(world, "pilot-demo-a:codex:1", before_finish=_publish_then(lambda d: d["nodes"][0].update(phase="missing")))
    summary = summarize(world)
    run = run_of(summary, "pilot-demo-a:codex:1")
    assert (run["SV"], run["E"], run["X"], run["errorCodes"]) == (0, 2, 2, ["reference"])
    assert target(summary, "structurallyValid")["met"] is False and summary["decision"]["value"] == "stop"


def test_unparseable_artifact_scores_zero_and_needs_no_review(world: World) -> None:
    def broken(workspace: Path, _evidence: Path) -> None:
        (workspace / "pilot.mlview.json").write_text('{"a": NaN}', encoding="utf-8")

    redo(world, "pilot-demo-a:codex:1", publish_artifact=False, before_finish=broken, review=False)
    summary = summarize(world)
    run = run_of(summary, "pilot-demo-a:codex:1")
    assert (run["SV"], run["E"], run["errorCodes"], run["reviewStatus"]) == (0, 0, ["invalid_json"], "not-applicable")
    assert summary["decision"]["value"] == "stop"
    code, _out, err = run_main(world, "review-template", "pilot-demo-a:codex:1", *pilot_args(world))
    assert code == 1 and "does not parse" in err


def test_inexact_anchor_counts_against_t2_only(world: World) -> None:
    redo(world, "pilot-demo-a:codex:1", before_finish=_publish_then(lambda d: d["evidence"][1].update(quote="not the source")))
    summary = summarize(world)
    run = run_of(summary, "pilot-demo-a:codex:1")
    assert (run["SV"], run["E"], run["X"], run["errorCodes"]) == (1, 2, 1, ["quote_mismatch"])
    assert [t["key"] for t in summary["targets"] if not t["met"]] == ["exactAnchors"]
    assert summary["decision"]["reasons"] == ["T2 exactAnchors: 7/8 (needs >= 1)"]


def test_stale_fingerprint_scores_zero(world: World) -> None:
    redo(world, "pilot-demo-a:codex:1",
         before_finish=_publish_then(lambda d: d["verification"]["files"].update({"train.py": "0" * 64})))
    run = run_of(summarize(world), "pilot-demo-a:codex:1")
    assert (run["SV"], run["X"], run["errorCodes"]) == (0, 2, ["stale_source"])


def test_unpublished_artifact_scores_zero(world: World) -> None:
    redo(world, "pilot-demo-a:codex:1", before_finish=_publish_then(lambda d: d.pop("verification")))
    run = run_of(summarize(world), "pilot-demo-a:codex:1")
    assert (run["SV"], run["errorCodes"]) == (0, ["unpublished"])


@pytest.mark.parametrize("status,failure", [("failed", "no-publication"), ("timed-out", "host-error"), ("blocked", "setup")])
def test_failed_timed_out_and_blocked_runs(world: World, status: str, failure: str) -> None:
    redo(world, "pilot-demo-b:codex:1", publish_artifact=False,
         session={"Status": status, "Failure": f"{failure} {EM} synthetic detail"})
    summary = summarize(world)
    run = run_of(summary, "pilot-demo-b:codex:1")
    assert (run["status"], run["SV"], run["ess"], run["ESS"]) == (status, 0, 0, 2)
    assert summary["decision"]["value"] == "stop"
    assert {"status": status, "failure": failure, "host": "codex", "task": "pilot-demo-b", "runs": 1} in summary["failures"]["counts"]
    markdown = wp.render_markdown(summary)
    assert f"Failures: pilot-demo-b:codex:1 {EM} {status} ({failure}: synthetic detail)." in markdown


# --------------------------------------------------------------------------------------------
# reviews (section 4.4, 4.5 F)


def _review_messages(world: World, run_id: str) -> list[str]:
    return [f"{p.level} {p.section}: {p.message}" for p in wp.check_file(world.evidence(run_id) / "review.md", root=world.root)]


def test_review_template_lists_every_element(world: World) -> None:
    text = (world.evidence("pilot-demo-b:codex:1") / "review.md").read_text(encoding="utf-8")
    forget(world, "pilot-demo-b:codex:1")
    do_run(world, "pilot-demo-b:codex:1", review=False)
    code, _out, _err = run_main(world, "review-template", "pilot-demo-b:codex:1", *pilot_args(world))
    pristine = (world.evidence("pilot-demo-b:codex:1") / "review.md").read_text(encoding="utf-8")
    keys = [line.split(": ")[0] for line in pristine.splitlines() if line.endswith(": pending")]
    assert keys == ["node:load", "node:step", "edge:e1", "finding:f1", "coverage", "configuration", "f1", "demo-b-f01",
                    "demo-b-f02", "demo-b-u01", *wp.USABILITY_KEYS, "task", "demo-b-d01", "Review"]
    assert "> demo-b-n01: A synthetic intentional behaviour." in pristine and "Reviewer:\n" in pristine
    assert "\nReviewer: Test" not in pristine and "Frozen denominator 2." in pristine
    assert "Reviewer: Test Reviewer (synthetic)" in text  # the base world filled it as a synthetic reviewer
    messages = _review_messages(world, "pilot-demo-b:codex:1")
    assert messages[:2] == ["TODO header: Reviewer is empty. Write the name of the person who reviewed this run.",
                            "TODO header: Date is empty. Write the review date as YYYY-MM-DD."]
    assert messages[-1] == 'TODO Task: Review is not complete. Write "Review: complete" when every verdict above is final.'
    code, _out, err = run_main(world, "review-template", "pilot-demo-b:codex:1", *pilot_args(world))
    assert code == 1 and "already exists; it is never overwritten" in err


@pytest.mark.parametrize("kwargs,expected", [
    ({"drop": (("Claims", "node:step"),)},
     'ERROR Claims: node:step has no line; every element needs exactly one: add "node:step: <verdict>".'),
    ({"drop": (("Essential facts", "demo-a-f02"),)}, 'ERROR Essential facts: demo-a-f02 has no line; add "demo-a-f02: <verdict>".'),
    ({"overrides": {("Essential facts", "demo-a-f01"): "covered"}},
     "ERROR Essential facts: demo-a-f01 is covered; name at least one pointer that shows it."),
    ({"overrides": {("Essential facts", "demo-a-f01"): "covered node:nowhere"}},
     'ERROR Essential facts: demo-a-f01: pointer "node:nowhere" does not resolve in the artifact.'),
    ({"overrides": {("Claims", "node:load"): "unsupported"}},
     f'ERROR Claims: node:load is unsupported; add " -- <reason>" (or " {EM} <reason>").'),
    ({"overrides": {("Claims", "node:load"): "aprove"}},
     'ERROR Claims: "node:load: aprove" is not a verdict. Write one of: no-claim, qualified, supported, unsupported.'),
    ({"overrides": {("Known unresolved", "demo-a-u01"): "not-stated coverage"}},
     "ERROR Known unresolved: demo-a-u01 is not-stated; it takes no pointers."),
    ({"overrides": {("Claims", "node:step"): "pending"}}, "ERROR Task: Review is complete, but 1 item(s) above are still to do."),
])
def test_review_problems_make_the_decision_incomplete(world: World, kwargs: dict, expected: str) -> None:
    run_id = "pilot-demo-a:codex:1"
    path = world.evidence(run_id) / "review.md"
    forget(world, run_id)
    do_run(world, run_id, review_kwargs=kwargs)
    assert expected in _review_messages(world, run_id), _review_messages(world, run_id)
    summary = summarize(world)
    assert summary["decision"]["value"] == "incomplete"
    assert run_of(summary, run_id)["reviewStatus"] == "problems" and path.exists()


def test_review_bound_to_another_artifact_or_revision(world: World) -> None:
    run_id = "pilot-demo-a:codex:1"
    path = world.evidence(run_id) / "review.md"
    text = path.read_text(encoding="utf-8")
    artifact = json.loads((world.evidence(run_id) / "record.json").read_text(encoding="utf-8"))["evidence"]["artifact"]["sha256"]
    path.write_text(text.replace(f"Artifact: {artifact}", "Artifact: " + "a" * 64), encoding="utf-8")
    assert any(m.startswith("ERROR header: the Artifact line does not match the sealed artifact")
               for m in _review_messages(world, run_id))
    path.write_text(text.replace("Reference: sha256:", "Reference: sha256:0"), encoding="utf-8")
    assert any("the Reference line does not match" in m for m in _review_messages(world, run_id))
    assert summarize(world)["decision"]["value"] == "incomplete"


def test_split_claims_splits_and_baseline_review_rules(world: World) -> None:
    run_id = "pilot-demo-a:codex:1"
    path = world.evidence(run_id) / "review.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("node:load: supported\n", f"node:load: supported\nnode:load#2: qualified {EM} partly\n"
                                                           "node:load#1: supported\nnode:ghost#2: supported\n"),
                    encoding="utf-8")
    messages = _review_messages(world, run_id)
    assert 'ERROR Claims: "node:load#1": split lines start at #2.' in messages
    assert any(m.startswith('ERROR Claims: "node:ghost#2" does not name an element') for m in messages)
    base = "pilot-demo-a:codex:baseline:1"
    bpath = world.evidence(base) / "review.md"
    btext = bpath.read_text(encoding="utf-8")
    bpath.write_text(btext.replace("response:1-2: supported", "response:1-999: supported\nresponse:2: no-claim")
                     .replace("## Usability\n", "## Usability\nlosses: clear\n"), encoding="utf-8")
    messages = _review_messages(world, base)
    lines = len((world.evidence(base) / "transcript.txt").read_text(encoding="utf-8").splitlines())
    assert f"ERROR Claims: \"response:1-999\" is outside the transcript's {lines} lines." in messages
    assert 'ERROR Usability: "losses" is not asked in a baseline review (only task).' in messages


def test_qualified_claims_and_no_claim_lines(world: World) -> None:
    run_id = "pilot-demo-a:codex:1"
    path = world.evidence(run_id) / "review.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("node:load: supported", f"node:load: qualified {EM} too broad")
                    .replace("node:step: supported", "node:step: no-claim"), encoding="utf-8")
    summary = summarize(world)
    run = run_of(summary, run_id)
    assert run["claims"]["observed"]["qualified"] == 1 and run["claims"]["noClaim"] == 1
    t3 = target(summary, "supportedClaimPrecision")
    assert (t3["numerator"], t3["denominator"], t3["met"]) == (22, 23, True)  # qualified = not-supported


# --------------------------------------------------------------------------------------------
# decisions (section 4.6)


def _set_review(world: World, run_id: str, old: str, new: str) -> None:
    path = world.evidence(run_id) / "review.md"
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


@pytest.mark.parametrize("key,edits", [
    ("supportedClaimPrecision", [("node:load: supported", f"node:load: unsupported {EM} synthetic"),
                                 ("edge:e1: supported", f"edge:e1: unsupported {EM} synthetic")]),
    ("essentialFactRecall", [("demo-a-f01: covered node:load", "demo-a-f01: missing"),
                             ("demo-a-f02: covered node:load", "demo-a-f02: partial node:load")]),
    ("knownUnresolvedQualified", [("demo-a-u01: stated coverage", "demo-a-u01: not-stated")]),
    ("highSeverityFalseAccusations", [("finding:f1: supported", f"finding:f1: unsupported {EM} synthetic")]),
])
def test_stop_for_each_reviewed_target(world: World, key: str, edits: list) -> None:
    for old, new in edits:
        _set_review(world, "pilot-demo-a:codex:1", old, new)
    summary = summarize(world)
    assert summary["decision"]["value"] == "stop"
    assert [t["key"] for t in summary["targets"] if not t["met"]] == [key]
    assert summary["decision"]["reasons"][0].startswith(f"{wp.TARGET_IDS[key]} {key}: ")


def test_itt_and_per_protocol_recall(world: World) -> None:
    redo(world, "pilot-demo-a:codex:1", publish_artifact=False, session={"Status": "failed", "Failure": "no-publication"})
    summary = summarize(world)
    t4 = target(summary, "essentialFactRecall")
    assert (t4["numerator"], t4["denominator"], t4["met"]) == (6, 8, False)
    assert summary["secondary"][0] == {"key": "essentialFactRecall", "id": "T4", "label": "per-protocol (reviewed runs only)",
                                       "numerator": 6, "denominator": 6, "value": 1.0}
    assert {t["key"] for t in summary["targets"] if not t["met"]} == {"structurallyValid", "essentialFactRecall",
                                                                      "knownUnresolvedQualified"}
    paired = next(p for p in summary["baselines"]["paired"] if p["task"] == "pilot-demo-a" and p["host"] == "codex")
    assert paired["skill"]["status"] == "failed" and paired["recallDifference"] == -1.0


def test_incomplete_with_early_stop_indicators(world: World) -> None:
    redo(world, "pilot-demo-a:codex:1", publish_artifact=False,
         session={"Status": "failed", "Failure": f"no-publication {EM} nothing published"})
    os.remove(world.evidence("pilot-demo-b:codex:1") / "record.json")
    os.remove(world.evidence("pilot-demo-b:claude-code:1") / "review.md")
    summary = summarize(world)
    decision = summary["decision"]
    assert decision["value"] == "incomplete"
    assert decision["reasons"][:2] == ["1 planned run(s) pending: pilot-demo-b:codex:1",
                                       "1 completed run(s) unreviewed: pilot-demo-b:claude-code:1"]
    assert "T1: pilot-demo-a:codex:1 failed (no-publication)" in decision["earlyStopIndicators"]
    code, _out, err = run_main(world, "summarize", *pilot_args(world), "--stage", "1", "--record")
    assert code == 1 and "the decision is incomplete; only go, stop, invalid can be recorded" in err


def test_invalidation_file_gives_invalid(world: World) -> None:
    path = world.root / wp.PILOT_REL / CAMPAIGN / "invalidation.md"
    path.write_text(f"# Invalidation: {CAMPAIGN}\nReviewer: {REVIEWER}\nDate: 2026-10-22\nScope: stage1\n"
                    "Reason: Synthetic invalidation for a test.\n", encoding="utf-8")
    summary = summarize(world)
    assert summary["decision"]["value"] == "invalid" and summary["inputs"]["invalidation"] == sha(path.read_bytes())
    path.write_text(f"# Invalidation: {CAMPAIGN}\nReviewer:\n", encoding="utf-8")
    assert any("invalidation.md needs Reviewer" in p for p in integrity_problems(world))


def test_corpus_absent_gives_incomplete(world: World, monkeypatch) -> None:
    monkeypatch.setenv("MLVIEW_PUBLIC_CORPUS_DIR", str(world.base / "no-corpus"))
    summary = summarize(world)
    assert summary["verification"]["complete"] is False and summary["decision"]["value"] == "incomplete"
    assert summary["verification"]["notes"][0].startswith("corpus absent for demo-a")


def test_compute_targets_policies_and_per_host_gate() -> None:
    def run(host, supported, qualified, unsupported, ess=2):
        return {"host": host, "status": "completed", "SV": 1, "E": 2, "X": 2, "ess": ess, "ESS": 2, "unk": 1, "UNK": 1,
                "fa": 0, "reviewed": True,
                "claims": {"observed": {"supported": supported, "qualified": qualified, "unsupported": unsupported},
                           "inferred": {"supported": 0, "qualified": 0, "unsupported": 0}}}

    thresholds = {"structurallyValid": 1.0, "exactAnchors": 1.0, "supportedClaimPrecision": 0.95,
                  "essentialFactRecall": 0.85, "knownUnresolvedQualified": 1.0, "highSeverityFalseAccusations": 0}
    runs = [run("codex", 8, 1, 1), run("claude-code", 10, 0, 0)]
    precision = {policy: next(t for t in wp.compute_targets(runs, thresholds, policy, False, HOSTS)
                              if t["key"] == "supportedClaimPrecision")
                 for policy in wp.QUALIFIED_POLICIES}
    assert {p: (t["numerator"], t["denominator"]) for p, t in precision.items()} == {
        "not-supported": (18, 20), "supported": (19, 20), "excluded": (18, 19)}
    runs = [run("codex", 40, 0, 0), run("codex", 40, 0, 0), run("claude-code", 19, 0, 1), run("claude-code", 20, 0, 0, ess=1)]
    pooled = {t["key"]: t for t in wp.compute_targets(runs, thresholds, "not-supported", False, HOSTS)}
    gated = {t["key"]: t for t in wp.compute_targets(runs, thresholds, "not-supported", True, HOSTS)}
    assert pooled["supportedClaimPrecision"]["met"] and pooled["essentialFactRecall"]["met"]  # 119/120 and 7/8
    assert gated["supportedClaimPrecision"]["met"] is True
    assert gated["essentialFactRecall"]["met"] is False
    assert gated["essentialFactRecall"]["perHost"]["claude-code"] == {"numerator": 3, "denominator": 4, "value": 0.75,
                                                                      "met": False}
    assert "perHost" not in gated["structurallyValid"]
    vacuous = [dict(r, UNK=0, unk=0) for r in runs]
    t5 = next(t for t in wp.compute_targets(vacuous, thresholds, "not-supported", False, HOSTS)
              if t["key"] == "knownUnresolvedQualified")
    assert t5["met"] is True and t5["vacuous"] is True and t5["value"] is None


# --------------------------------------------------------------------------------------------
# Stage 2 guards


def test_stage_2_guards(world: World) -> None:
    code, _out, err = run_main(world, "summarize", *pilot_args(world), "--stage", "1", "--record")
    assert code == 0, err
    git(world.root, "add", "-A")
    git(world.root, "commit", "--quiet", "-m", "synthetic stage 1 summary")
    do_run(world, "pilot-demo-a:codex:2", session={"Started": "2026-10-25T09:00:00Z", "Ended": "2026-10-25T09:10:00Z"})
    do_run(world, "pilot-demo-a:codex:3", session={"Started": "2026-10-11T09:00:00Z", "Ended": "2026-10-11T09:10:00Z"})
    summary = summarize(world, "all")
    assert run_of(summary, "pilot-demo-a:codex:2")["status"] == "completed"
    assert run_of(summary, "pilot-demo-a:codex:3")["invalidReasons"] == [
        "Stage 2 run started before the committed Stage 1 summary was generated"]
    assert summary["decision"]["value"] == "incomplete" and target(summary, "structurallyValid")["denominator"] == 12
    assert "T1: pilot-demo-a:codex:3 invalid (Stage 2 run started before the committed Stage 1 summary was generated)" \
        in summary["decision"]["earlyStopIndicators"]
    git(world.root, "rm", "--quiet", f"{wp.PILOT_REL}/{CAMPAIGN}/stage1-summary.json", f"{wp.PILOT_REL}/{CAMPAIGN}/stage1-summary.md")
    git(world.root, "commit", "--quiet", "-m", "synthetic removal")
    reasons = run_of(summarize(world, "all"), "pilot-demo-a:codex:2")["invalidReasons"]
    assert reasons == ["Stage 2 run without a committed Stage 1 go summary (there is no committed stage1-summary.json)"]
    assert summarize(world, "1")["decision"]["value"] == "go"  # Stage 1 ignores the repeats


# --------------------------------------------------------------------------------------------
# guarantees


def test_no_tool_output_contains_a_decision_or_approval(world: World, tmp_path: Path) -> None:
    template = wp.session_template("pilot-demo-a:codex:1", "skill").decode("utf-8")
    assert "Status: pending" in template and "Reviewer" not in template
    base = "pilot-demo-a:codex:baseline:1"
    forget(world, base)
    do_run(world, base, review=False)
    run_main(world, "review-template", base, *pilot_args(world))
    text = (world.evidence(base) / "review.md").read_text(encoding="utf-8")
    values = [line.split(": ", 1)[1] for line in text.splitlines() if ": " in line and not line.startswith((">", "#"))]
    assert set(values) - {"pending"} == {base, json.loads((world.evidence(base) / "record.json").read_text(encoding="utf-8"))["evidence"]["transcript"]["sha256"],
                                          json.loads((world.evidence(base) / "record.json").read_text(encoding="utf-8"))["referenceRevision"]}
    assert "Reviewer:\n" in text and "Review: pending" in text
    assert "complete" not in text.replace('"Review: complete" when', "")
    summary = summarize(world)
    assert summary["pilotApproved"] is False and summary["decision"]["label"] == wp.NOT_APPROVAL


def test_caveats_match_the_specification_for_the_committed_manifest() -> None:
    texts = wp.caveats(8, 3, 3)
    assert texts[0] == ("The 24 Stage 1 runs are 8 pinned scenarios \u00d7 3 configured host workflows, one session each. "
                        "They are not a sample of repositories or sessions, and the results describe these scenarios only.")
    assert texts[1].endswith("because 8 task clusters cannot support them.")
    assert texts[3] == ("Stage 2 repeats measure within-scenario variation; 72 runs are not 72 independent tasks "
                        '(evals/workflow/README.md, "Review and adjudicate").')


def test_cited_readme_sections_exist() -> None:
    """Tool strings cite README sections by heading (line numbers go stale when a README is edited)."""
    cited = re.findall(r'(evals/workflow/README\.md|CANDIDATE_PROTOCOL\.md|REVIEW_GUIDE\.md), "([^"]+)"',
                       "\n".join((TOOLS / name).read_text(encoding="utf-8")
                                  for name in ("workflow_pilot.py", "workflow_decisions.py")))
    assert {doc for doc, _heading in cited} == {"evals/workflow/README.md", "CANDIDATE_PROTOCOL.md", "REVIEW_GUIDE.md"}
    files = {"evals/workflow/README.md": ROOT / "evals/workflow/README.md",
             "CANDIDATE_PROTOCOL.md": ROOT / "evals/workflow/CANDIDATE_PROTOCOL.md",
             "REVIEW_GUIDE.md": ROOT / "evals/workflow/reference-candidates/REVIEW_GUIDE.md"}
    for doc, heading in sorted(set(cited)):
        headings = [line.lstrip("#").strip() for line in files[doc].read_text(encoding="utf-8").splitlines()
                    if line.startswith("#")]
        assert heading in headings, (doc, heading)
    assert "(README.md:" not in "\n".join(wp.caveats(8, 3, 3)) + wp.GO_TEXT


# --------------------------------------------------------------------------------------------
# Round 1 review regressions (every value synthetic)


def test_a_deleted_record_cannot_be_resealed_with_other_facts(world: World) -> None:
    run_id = "pilot-demo-a:codex:1"
    evidence = world.evidence(run_id)
    timed_out = {"Status": "timed-out", "Failure": "repair-budget -- ran out (synthetic)", "Active minutes": "35"}
    redo(world, run_id, session=timed_out)
    sealed = (evidence / "session.md").read_bytes()
    assert (evidence / "partial-artifact.mlview.json").is_file() and (evidence / "finish-state.json").is_file()
    os.remove(evidence / "record.json")
    (evidence / "session.md").write_text(session_text(run_id), encoding="utf-8")
    shutil.copy(evidence / "partial-artifact.mlview.json", evidence / "artifact.mlview.json")
    code, _out, err = run_main(world, "run-finish", run_id, *pilot_args(world))
    assert code == 1 and "session.md changed after run-finish removed the workspace" in err, err
    (evidence / "session.md").write_bytes(sealed)
    code, _out, err = run_main(world, "run-finish", run_id, *pilot_args(world))
    assert code == 1 and "artifact.mlview.json was not written by run-finish" in err, err
    os.remove(evidence / "artifact.mlview.json")
    code, _out, err = run_main(world, "run-finish", run_id, *pilot_args(world))
    assert code == 0, err
    assert json.loads((evidence / "record.json").read_text(encoding="utf-8"))["session"]["status"] == "timed-out"


def test_a_record_deleted_after_an_amendment_is_never_resealed(world: World) -> None:
    run_id = "pilot-demo-a:codex:1"
    evidence = world.evidence(run_id)
    (evidence / "session.md").write_text(session_text(run_id, **{"Active minutes": "16"}), encoding="utf-8")
    assert run_main(world, "run-finish", run_id, *pilot_args(world), "--amend", "typo (synthetic)")[0] == 0
    os.remove(evidence / "record.json")
    code, _out, err = run_main(world, "run-finish", run_id, *pilot_args(world))
    assert code == 1 and "record.previous-*.json exist: the sealed record was deleted" in err, err
    code, _out, err = run_main(world, "run-finish", run_id, *pilot_args(world), "--amend", "from D:/pilot (synthetic)")
    assert code == 1 and "the amendment reason contains a machine path" in err, err


def test_sealed_workspace_lists_must_match_the_hashed_evidence(world: World) -> None:
    run_id = "pilot-demo-a:claude-code:1"
    evidence = world.evidence(run_id)
    original = (evidence / "record.json").read_bytes()
    edit_json(evidence / "record.json", lambda v: v["workspace"]["changedProjectFiles"].append(
        {"path": "train.py", "change": "modified", "file": None, "sha256": None}))
    problems = integrity_problems(world)
    assert any("record.json workspace lists differ from workspace-changes.json" in p for p in problems), problems
    (evidence / "record.json").write_bytes(original)
    (evidence / "record.previous-3.json").write_bytes(original)
    assert any("record.previous-3.json is not referenced by record.json amendments" in p for p in integrity_problems(world))
    os.remove(evidence / "record.previous-3.json")
    assert summarize(world)["decision"]["value"] == "go"


def test_workspace_changes_are_measured_against_the_pinned_files(world: World) -> None:
    run_id = "pilot-demo-a:codex:1"

    def edit_both(workspace: Path, evidence: Path) -> None:
        (workspace / "train.py").write_text("tampered = True  # synthetic\n", encoding="utf-8")
        before = json.loads((evidence / "workspace-before.json").read_text(encoding="utf-8"))
        before["train.py"] = sha(b"tampered = True  # synthetic\n")
        (evidence / "workspace-before.json").write_bytes(er.canonical_json(before))

    redo(world, run_id, before_finish=edit_both)
    run = run_of(summarize(world), run_id)
    assert run["status"] == "invalid"
    assert "workspace-before.json differs from the pinned files for 1 path(s) (train.py)" in run["invalidReasons"]
    assert "1 project file(s) changed in the workspace (train.py)" in run["invalidReasons"]


def test_a_host_settings_file_is_reported_not_invalidating(world: World) -> None:
    def settings(workspace: Path, _evidence: Path) -> None:
        (workspace / ".claude").mkdir(exist_ok=True)
        (workspace / ".claude/settings.local.json").write_text('{"permissions": {"allow": []}}\n', encoding="utf-8")

    redo(world, "pilot-demo-b:claude-code:1", before_finish=settings)
    redo(world, "pilot-demo-b:codex:1", before_finish=settings)
    summary = summarize(world)
    claude = run_of(summary, "pilot-demo-b:claude-code:1")
    assert claude["status"] == "completed" and any(".claude/settings.local.json" in w for w in claude["warnings"])
    record = json.loads((world.evidence("pilot-demo-b:claude-code:1") / "record.json").read_text(encoding="utf-8"))
    assert [entry["path"] for entry in record["workspace"]["hostFiles"]] == [".claude/settings.local.json"]
    assert record["workspace"]["changedProjectFiles"] == [] and record["workspace"]["hostFiles"][0]["file"]
    codex = run_of(summary, "pilot-demo-b:codex:1")
    assert codex["status"] == "invalid" and "1 project file(s) changed in the workspace (.claude/settings.local.json)" \
        in codex["invalidReasons"]


def test_mlview_files_in_a_baseline_workspace_invalidate_it(world: World) -> None:
    run_id = "pilot-demo-a:codex:baseline:1"
    redo(world, run_id, before_finish=lambda ws, _ev: (ws / "answer.mlview.json").write_text("{}\n", encoding="utf-8"))
    summary = summarize(world)
    assert summary["decision"]["value"] == "go"  # baselines never gate
    run = next(p["baseline"] for p in summary["baselines"]["paired"] if p["task"] == "pilot-demo-a" and p["host"] == "codex")
    assert run["status"] == "invalid"
    record = json.loads((world.evidence(run_id) / "record.json").read_text(encoding="utf-8"))
    assert [entry["path"] for entry in record["workspace"]["changedProjectFiles"]] == ["answer.mlview.json"]


def test_a_baseline_is_not_held_to_the_skill_invocation(world: World, fresh: World) -> None:
    summary = summarize(world)
    baseline = next(p["baseline"] for p in summary["baselines"]["paired"] if p["task"] == "pilot-demo-a")
    assert baseline["status"] == "completed"
    record = json.loads((world.evidence("pilot-demo-a:codex:baseline:1") / "record.json").read_text(encoding="utf-8"))
    assert record["session"]["invocation"] == "none (plain prompt; no skill) (synthetic)"
    code, out, err = run_main(fresh, "run-prepare", "pilot-demo-a:codex:baseline:1", *pilot_args(fresh))
    assert code == 0, err
    assert "no skill invocation" in out and "do not use the skill invocation" in out and "synthetic codex invocation" not in out


def test_unreviewed_baselines_block_recording_and_show_no_difference(world: World) -> None:
    base = "pilot-demo-a:codex:baseline:1"
    os.remove(world.evidence(base) / "review.md")
    summary = summarize(world)
    assert summary["decision"]["value"] == "go"
    baselines = summary["baselines"]
    assert baselines["unreviewed"] == [base] and baselines["complete"] is False
    paired = next(p for p in baselines["paired"] if p["task"] == "pilot-demo-a" and p["host"] == "codex")
    assert paired["baseline"]["status"] == "unreviewed" and paired["recallDifference"] is None
    assert f"Unreviewed: {base}." in wp.render_markdown(summary)
    code, _out, err = run_main(world, "summarize", *pilot_args(world), "--stage", "1", "--record")
    assert code == 1 and f"the planned baselines are not complete (unreviewed: {base})" in err, err
    (world.evidence(base) / "review.md").write_text("# Run review: somewhere else\n", encoding="utf-8")
    summary = summarize(world)
    assert summary["baselines"]["reviewProblems"] == [base]
    assert next(r for r in summary["baselines"]["runs"] if r["id"] == base)["reviewProblems"] >= 1


def test_a_forged_stage1_go_does_not_unlock_stage_2(world: World, tmp_path: Path) -> None:
    campaign_dir = world.root / wp.PILOT_REL / CAMPAIGN
    redo(world, "pilot-demo-a:codex:1", publish_artifact=False,
         session={"Status": "failed", "Failure": "no-publication -- nothing published (synthetic)"})
    real = summarize(world)
    assert real["decision"]["value"] == "stop"
    forged = json.loads(er.canonical_json(real))
    forged["decision"]["value"] = "go"
    (campaign_dir / "stage1-summary.json").write_bytes(er.canonical_json(forged))
    (campaign_dir / "stage1-summary.md").write_bytes(wp.render_markdown(forged).encode("utf-8"))
    commit_files(world.root, {}, "synthetic forged go")
    code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(world))
    assert code == 1 and "a re-computation of Stage 1 from the sealed evidence gives stop, not go" in err, err
    # A pilot directory without the Stage 1 evidence does not re-verify the go, and says so (SPECDOCS2-4, STATS-F5).
    other = tmp_path / "other-pilot"
    other.mkdir()
    code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:codex:2", "--campaign", CAMPAIGN,
                               "--pilot-dir", str(other))
    assert code == 1 and "8 Stage 1 run(s) of the summary have no sealed record in this pilot directory, for example " \
                         "pilot-demo-a:claude-code:1" in err and "use the pilot directory that holds the Stage 1 " \
                         "evidence" in err, err
    assert not (other / "evidence").exists() and not (other / "workspaces").exists()
    (campaign_dir / "stage1-summary.json").write_text('{"decision": {"value": "go"}}\n', encoding="utf-8")
    commit_files(world.root, {}, "synthetic hand-written summary")
    code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(world))
    assert code == 1 and 'is not a "mlview-pilot-summary/1" Stage 1 summary' in err, err


def test_a_changed_stage1_review_holds_stage_2_without_invalidating_it(world: World) -> None:
    """After the Stage 1 record, a review.md re-saved (CRLF), given trailing spaces, blank lines or a '>' note keeps
    its normalized hash and does no harm; a changed verdict is named with its run and file, blocks Stage 2 with the
    remedy and makes the all-stage summary incomplete instead of marking Stage 2 runs invalid, also when the
    re-computed decision is stop (HONEST-F2, SPECDOCS-F1, STATS-F2, STATS-F5)."""
    code, _out, err = run_main(world, "summarize", *pilot_args(world), "--stage", "1", "--record")
    assert code == 0 and "every Stage 1 review.md must keep its content: only '>' notes, line endings, trailing " \
                         "spaces and blank lines may change" in err, err
    commit_files(world.root, {}, "synthetic stage 1 summary")
    later = {"Started": "2026-10-25T09:00:00Z", "Ended": "2026-10-25T09:10:00Z"}
    do_run(world, "pilot-demo-a:codex:2", session=later)
    review = world.evidence("pilot-demo-b:codex:1") / "review.md"
    baseline_review = world.evidence("pilot-demo-a:codex:baseline:1") / "review.md"
    original = review.read_bytes()
    review.write_bytes(original.replace(b"\n", b"\r\n"))  # an editor's re-save with CRLF
    baseline_review.write_bytes(baseline_review.read_bytes().replace(b"\n## ", b"   \n\n## ")
                                + b"> a note added later (synthetic)\n")
    assert run_main(world, "run-prepare", "pilot-demo-a:claude-code:2", *pilot_args(world))[0] == 0
    assert run_of(summarize(world, "all"), "pilot-demo-a:codex:2")["status"] == "completed"
    # A changed verdict: named, with the remedy; Stage 2 stays valid, the all-stage summary incomplete.
    review.write_bytes(original.replace(b"demo-b-u01: stated coverage", b"demo-b-u01: not-stated"))
    assert summarize(world)["decision"]["value"] == "stop"
    code, _out, err = run_main(world, "run-prepare", "pilot-demo-b:claude-code:2", *pilot_args(world))
    assert code == 1 and "1 Stage 1 review(s) changed since the summary was recorded: pilot-demo-b:codex:1 " \
                         "(evidence/pilot-demo-b.codex.1/review.md) changed (normalized sha256 " in err, err
    assert "pilot-demo-a:codex:baseline:1" not in err and "Stage 1 reviews are final once the Stage 1 summary is " \
                                                          "recorded" in err, err
    summary = summarize(world, "all")
    assert summary["decision"]["value"] == "incomplete"
    assert "the committed Stage 1 go is not re-verified here (see the verification notes)" in summary["decision"]["reasons"]
    assert not [run["id"] for run in summary["runs"] if run["status"] == "invalid"]
    assert any("changed since the summary was recorded: pilot-demo-b:codex:1 (evidence/pilot-demo-b.codex.1/review.md)"
               in note for note in summary["verification"]["notes"]), summary["verification"]["notes"]
    with pytest.raises(wp.PilotError, match="the decision is incomplete"):
        wp.record_summary(world.root, summary)
    review.write_bytes(original)
    assert run_main(world, "run-prepare", "pilot-demo-b:claude-code:2", *pilot_args(world))[0] == 0


UNSENT = {"Status": "failed", "Failure": "host-error -- the host crashed before the prompt (synthetic)",
          "Prompt sent": "no", "Repair rounds": "0"}
UNSENT_TRANSCRIPT = "The host crashed before the prompt was sent (synthetic).\n"


def test_a_failed_run_is_retried_only_through_the_ledger(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = "pilot-demo-b:codex:1"
    code, _out, err = run_main(world, "run-prepare", run_id, *pilot_args(world), "--retry", "again (synthetic)")
    assert code == 1 and "a completed run is never retried" in err, err
    redo(world, run_id, publish_artifact=False, session=UNSENT, transcript=UNSENT_TRANSCRIPT)
    # The synthetic policy allows no infrastructure retry, so run-prepare refuses one (STATS3-2) ...
    code, _out, err = run_main(world, "run-prepare", run_id, *pilot_args(world), "--retry", "the host crashed (synthetic)")
    assert code == 1 and "the run policy allows 0 infrastructure retries; attempt 1 of pilot-demo-b:codex:1 is kept " \
                         "and counted" in err, err
    code, _out, err = run_main(world, "run-prepare", run_id, *pilot_args(world))
    assert code == 1 and "the run policy allows 0 infrastructure retries, so attempt 1 is kept and counted" in err, err
    assert "--retry" not in err
    # ... and a retry prepared around that rule is counted invalid by summarize.
    real = wp.load_campaign

    def lenient(root: Path, name: str) -> wp.Campaign:
        campaign = real(root, name)
        campaign.retries = 1  # stands in for a retry prepared around the policy
        return campaign

    with monkeypatch.context() as patched:
        patched.setattr(wp, "load_campaign", lenient)
        code, out, err = run_main(world, "run-prepare", run_id, *pilot_args(world), "--retry",
                                  "the host crashed (synthetic)")
        assert code == 0, err
    earlier = world.pilot / "evidence" / "pilot-demo-b.codex.1.attempt-1"
    evidence = world.evidence(run_id)
    workspace = world.pilot / "workspaces" / "pilot-demo-b.codex.1.attempt-2"
    assert (earlier / "record.json").is_file() and workspace.is_dir() and not world.workspace(run_id).exists()
    assert "Prior attempts: 1" in (evidence / "session.md").read_text(encoding="utf-8")
    publish(workspace, "codex", "pilot-demo-b")
    prompt = (evidence / "PROMPT.txt").read_text(encoding="utf-8")
    (evidence / "transcript.txt").write_text(prompt + "\nThe loop runs.\n", encoding="utf-8")
    (evidence / "ui-log.md").write_text("Synthetic UI checklist.\n", encoding="utf-8")
    (evidence / "session.md").write_text(session_text(run_id), encoding="utf-8")
    code, _out, err = run_main(world, "run-finish", run_id, *pilot_args(world))
    assert code == 1 and "records 1 earlier attempt(s); write Prior attempts: 1" in err, err
    (evidence / "session.md").write_text(session_text(run_id, **{"Prior attempts": "1"}), encoding="utf-8")
    code, _out, err = run_main(world, "run-finish", run_id, *pilot_args(world))
    assert code == 0, err
    assert run_main(world, "review-template", run_id, *pilot_args(world))[0] == 0
    fill_review(evidence / "review.md")
    run = run_of(summarize(world), run_id)
    assert run["status"] == "invalid" and "prior attempts 1 exceed the infrastructure retries (0)" in run["invalidReasons"]
    ledger = [json.loads(line) for line in (world.pilot / wp.LEDGER_FILE).read_text(encoding="utf-8").splitlines()]
    assert [(e["attempt"], e["reason"]) for e in ledger if e["run"] == run_id] == [(1, None), (2, "the host crashed (synthetic)")]
    shutil.rmtree(earlier)
    assert any("the kept earlier attempts none differ from the 1 earlier attempt(s)" in p for p in integrity_problems(world))


def test_erased_evidence_is_never_prepared_again(world: World) -> None:
    run_id = "pilot-demo-a:codex:1"
    shutil.rmtree(world.evidence(run_id))
    code, _out, err = run_main(world, "run-prepare", run_id, *pilot_args(world))
    assert code == 1 and "was already prepared" in err
    assert any("records 1 preparation(s) but evidence/pilot-demo-a.codex.1 is missing" in p for p in integrity_problems(world))


def test_early_stop_does_not_count_an_unreviewable_run_as_open(world: World) -> None:
    def broken(workspace: Path, _evidence: Path) -> None:
        (workspace / "pilot.mlview.json").write_text('{"a": NaN}', encoding="utf-8")

    redo(world, "pilot-demo-a:codex:1", publish_artifact=False, before_finish=broken, review=False)
    os.remove(world.evidence("pilot-demo-b:codex:1") / "record.json")
    indicators = summarize(world)["decision"]["earlyStopIndicators"]
    assert "T4: at most 6/8 can still be reached" in indicators and "T5: at most 3/4 can still be reached" in indicators


def test_split_claims_reject_leading_zeros_and_repeats(world: World) -> None:
    run_id = "pilot-demo-a:codex:1"
    forget(world, run_id)
    do_run(world, run_id, review=False)
    run_main(world, "review-template", run_id, *pilot_args(world))
    path = world.evidence(run_id) / "review.md"
    fill_review(path)
    path.write_text(path.read_text(encoding="utf-8").replace("node:load: supported\n",
                                                               "node:load: supported\nnode:load#02: supported\n"),
                    encoding="utf-8")
    assert any("write #2, #3, ... without leading zeros" in m for m in _review_messages(world, run_id))
    base = "pilot-demo-a:codex:baseline:1"
    forget(world, base)
    do_run(world, base, review_kwargs={"baseline_claims": ("response:1-2: supported", "response:01-2: supported",
                                                           "response:1-2#2: supported", "response:1-2#02: supported")})
    messages = _review_messages(world, base)
    assert sum("without leading zeros" in m for m in messages) == 2, messages


def test_disputed_denominator_items_include_flags_the_resolution_dropped() -> None:
    reference = {"essentialFactIds": ["x-f01"], "knownUnresolved": [{"id": "x-u01", "runsMustState": False}],
                 "disputes": [
                     {"item": "x-f01", "primary": {"decision": "accept", "essential": True},
                      "second": {"decision": "reject"}, "resolution": "kept (synthetic)"},
                     {"item": "x-f02", "primary": {"decision": "accept", "essential": False},
                      "second": {"decision": "accept", "essential": True}, "resolution": "not essential (synthetic)"},
                     {"item": "x-u01", "primary": {"decision": "accept", "runsMustState": False},
                      "second": {"decision": "accept", "runsMustState": True}, "resolution": "optional (synthetic)"},
                     {"item": "x-n01", "primary": {"decision": "accept"}, "second": {"decision": "reject"},
                      "resolution": "kept (synthetic)"}]}
    campaign = type("Campaign", (), {"references": {"pilot-x": reference}})()
    found = wp._disputed_items(campaign, ["pilot-x"])
    assert [(d["item"], d["kind"], d["inDenominator"]) for d in found] == [
        ("x-f01", "essential", True), ("x-f02", "essential", False), ("x-u01", "runsMustState", False)]
    assert all("resolution" not in d for d in found)
    # A second-review addition adopted under the primary's own ID is inside the denominators (OWNERUX2-2).
    reference["essentialFactIds"].append("x-h01")
    reference["knownUnresolved"].append({"id": "x-hu01", "runsMustState": True})
    reference["disputes"] = [
        {"item": "x-s-h01", "primary": {"decision": "added", "basis": "observed", "essential": True},
         "second": {"decision": "added", "basis": "observed", "essential": True}, "adoptedAs": "x-h01",
         "resolution": "adopted as x-h01 (synthetic)"},
        {"item": "x-s-hu01", "primary": {"decision": "added", "runsMustState": True},
         "second": {"decision": "added", "runsMustState": True}, "adoptedAs": "x-hu01",
         "resolution": "adopted as x-hu01 (synthetic)"},
        {"item": "x-s-h02", "primary": None, "second": {"decision": "added", "basis": "observed", "essential": True},
         "resolution": "not supported (synthetic)"}]
    found = wp._disputed_items(campaign, ["pilot-x"])
    assert [(d["item"], d["kind"], d["inDenominator"], d.get("adoptedAs")) for d in found] == [
        ("x-s-h01", "essential", True, "x-h01"), ("x-s-hu01", "runsMustState", True, "x-hu01"),
        ("x-s-h02", "essential", False, None)]
    assert wp._disputed_essential(campaign, ["pilot-x"]) == [{"task": "pilot-x", "item": "x-s-h01", "adoptedAs": "x-h01"}]


def test_percentages_never_round_up_to_a_threshold() -> None:
    assert wp._pct(816, 859) == "94.9%" and wp._pct(1, 3) == "33.3%" and wp._pct(2, 3) == "66.6%"
    assert wp._fmt_ratio({"numerator": 816, "denominator": 859}) == "816/859 (94.9%)"
    # The Sensitivity section floors too (SPECDOCS2-5); the epsilon keeps exact tenths such as 0.95.
    assert [wp._fmt_value(v) for v in (816 / 859, 0.8496, 0.94951, 0.95, 0.85, 1.0, 0.0, None)] == [
        "94.9%", "84.9%", "94.9%", "95.0%", "85.0%", "100.0%", "0.0%", "n/a"]
    assert all(wp._fmt_value(n / d) == wp._pct(n, d) for d in range(1, 400) for n in range(0, d + 1))


def test_frozen_references_must_come_from_committed_decisions(world: World) -> None:
    campaign = wp.load_campaign(world.root, CAMPAIGN)
    freeze = copy.deepcopy(campaign.freeze)
    del freeze["decisionFiles"]["evals/workflow/decisions/pilot-demo-a.md"]
    freeze["candidateLedgers"] = {}
    references = copy.deepcopy(campaign.references)
    references["pilot-demo-b"]["reviews"][0]["sha256"] = "0" * 64
    problems = wp._decision_binding(world.root, campaign.commit, freeze, campaign.heldout, references, campaign.policy)
    assert "freeze.json: decisionFiles has no evals/workflow/decisions/pilot-demo-a.md" in problems
    assert "freeze.json: candidateLedgers has no evals/workflow/reference-candidates/pilot-demo-a.json" in problems
    assert any("reference/pilot-demo-b.json: review 'evals/workflow/decisions/pilot-demo-b.md' is not a frozen" in p
               for p in problems)
    assert wp._decision_binding(world.root, campaign.commit, campaign.freeze, campaign.heldout, campaign.references,
                                campaign.policy) == []


def test_a_forward_slash_drive_path_is_never_recorded(world: World) -> None:
    summary = summarize(world)
    summary["caveats"].append("evidence copied from D:/mlview-pilot by hand (synthetic)")
    with pytest.raises(wp.PilotError, match="machine path"):
        wp.record_summary(world.root, summary)


# --------------------------------------------------------------------------------------------
# Round 2: retries, earlier attempts and recorded summaries (synthetic data only)


def finish_retry(world: World, run_id: str, prior: int = 1) -> None:
    """Publish, seal and review the retried attempt that run-prepare --retry prepared (synthetic)."""
    evidence = world.evidence(run_id)
    task, host = run_id.split(":")[:2]
    publish(world.pilot / "workspaces" / f"{er.run_dir_name(run_id)}.attempt-{prior + 1}", host, task)
    prompt = (evidence / "PROMPT.txt").read_text(encoding="utf-8")
    (evidence / "transcript.txt").write_text(prompt + "\nThe loop runs 40 steps.\n", encoding="utf-8")
    (evidence / "ui-log.md").write_text("Synthetic UI checklist.\n", encoding="utf-8")
    (evidence / "session.md").write_text(session_text(run_id, **{"Prior attempts": str(prior)}), encoding="utf-8")
    code, out, err = run_main(world, "run-finish", run_id, *pilot_args(world))
    assert code == 0, out + err
    assert run_main(world, "review-template", run_id, *pilot_args(world))[0] == 0
    fill_review(evidence / "review.md")


@pytest.fixture
def retry_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    """A Stage 1 world whose synthetic policy allows one infrastructure retry (no human agreed to it)."""
    world = build_world(tmp_path / "retry", policy=make_policy(**{"budget.infrastructureRetries": 1}))
    patches(monkeypatch, world)
    for run_id in stage1_ids(baselines=False):
        do_run(world, run_id)
    return world


@pytest.mark.parametrize("session, why", [
    ({"Status": "timed-out", "Failure": "repair-budget -- ran out (synthetic)", "Active minutes": "35"}, "it timed out"),
    ({"Status": "failed", "Failure": "repair-budget -- two repairs did not help (synthetic)"},
     "it failed with repair-budget"),
    ({"Status": "failed", "Failure": "no-publication -- nothing published (synthetic)"}, "it failed with no-publication"),
    ({"Status": "failed", "Failure": "host-error -- crashed (synthetic)", "Prompt sent": "yes"},
     'its session says "Prompt sent: yes"'),
    ({"Status": "blocked", "Failure": "host-error -- crashed (synthetic)", "Repair rounds": "0"},
     'its session does not say "Prompt sent: no"'),
])
def test_a_failure_after_the_prompt_was_sent_is_never_retried(retry_world: World, session: dict, why: str) -> None:
    """--retry replaces only an attempt whose prompt never reached the host (INTEGRITY2-2, SPECDOCS2-1)."""
    run_id = "pilot-demo-a:codex:1"
    redo(retry_world, run_id, publish_artifact=False, session=session, transcript=UNSENT_TRANSCRIPT)
    stop = summarize(retry_world)
    code, _out, err = run_main(retry_world, "run-prepare", run_id, *pilot_args(retry_world), "--retry", "again (synthetic)")
    assert code == 1 and f"attempt 1 of {run_id} cannot be retried: {why}; a retry is allowed only if the prompt was " \
                         "never sent" in err, err
    assert ("run-finish pilot-demo-a:codex:1 --campaign pilot-01 --amend" in err) == ("does not say" in why)
    assert not (retry_world.pilot / "evidence" / "pilot-demo-a.codex.1.attempt-1").exists()
    assert summarize(retry_world)["decision"] == stop["decision"] and stop["decision"]["value"] == "stop"


def test_a_prompt_sent_no_session_must_be_consistent(tmp_path: Path) -> None:
    evidence = tmp_path / "ev"
    evidence.mkdir()
    (evidence / "PROMPT.txt").write_text("Explain the synthetic loop.\n", encoding="utf-8")
    (evidence / "transcript.txt").write_text("user: Explain the synthetic\nloop.\n", encoding="utf-8")
    cases = [({"Status": "timed-out", "Failure": "repair-budget -- x (synthetic)", "Prompt sent": "no"},
              'Status is timed-out, so the prompt was sent; write "Prompt sent: yes".'),
             ({"Status": "failed", "Failure": "no-publication -- x (synthetic)", "Prompt sent": "no"},
              'Failure is no-publication, so the prompt was sent; write "Prompt sent: yes".'),
             ({"Status": "completed", "Prompt sent": "no"}, 'Status is completed, so the prompt was sent; write '
                                                            '"Prompt sent: yes".'),
             ({"Status": "failed", "Failure": "host-error -- x (synthetic)", "Prompt sent": "maybe"},
              "Prompt sent must be yes or no."),
             ({"Status": "failed", "Failure": "host-error -- x (synthetic)", "Prompt sent": "no"},
              'the transcript contains PROMPT.txt, so the prompt was sent; write "Prompt sent: yes".')]
    for values, message in cases:
        (evidence / "session.md").write_text(session_text("pilot-demo-a:codex:baseline:1", **values), encoding="utf-8")
        assert message in [p.message for p in wp.check_file(evidence / "session.md")], values
    (evidence / "transcript.txt").write_text("The host crashed first (synthetic).\n", encoding="utf-8")
    assert not [p for p in wp.check_file(evidence / "session.md") if "Prompt sent" in p.message]
    assert "Prompt sent:" in wp.session_template("pilot-demo-a:codex:1", "skill").decode("utf-8")


def test_a_completed_attempt_amended_to_a_failure_is_never_retried(retry_world: World) -> None:
    """An amendment chain that was ever completed counts as a completed session (INTEGRITY2-2, P2).
    The sealed transcript is kept, and a captured artifact rules out "Prompt sent: no" (INTEGRITY3-3)."""
    run_id = "pilot-demo-b:codex:1"
    evidence = retry_world.evidence(run_id)
    sealed = (evidence / "transcript.txt").read_bytes()
    (evidence / "session.md").write_text(session_text(run_id, **UNSENT), encoding="utf-8")
    (evidence / "transcript.txt").write_text(UNSENT_TRANSCRIPT, encoding="utf-8")
    code, out, err = run_main(retry_world, "run-finish", run_id, *pilot_args(retry_world), "--amend",
                              "the host crashed (synthetic)")
    assert code == 1 and "the transcript sealed earlier (transcript.txt, sha256 " in err, out + err
    (evidence / "transcript.txt").write_bytes(sealed)
    code, out, err = run_main(retry_world, "run-finish", run_id, *pilot_args(retry_world), "--amend",
                              "the host crashed (synthetic)")
    assert code == 1 and "the transcript contains PROMPT.txt, so the prompt was sent" in out, out + err
    (evidence / "session.md").write_text(session_text(run_id, **dict(UNSENT, **{"Prompt sent": "yes"})), encoding="utf-8")
    code, out, err = run_main(retry_world, "run-finish", run_id, *pilot_args(retry_world), "--amend",
                              "the host crashed (synthetic)")
    assert code == 0, out + err
    code, _out, err = run_main(retry_world, "run-prepare", run_id, *pilot_args(retry_world), "--retry", "x (synthetic)")
    assert code == 1 and "attempt 1 of pilot-demo-b:codex:1 completed before it was amended; a completed run is never " \
                         "retried" in err, err


def test_a_retry_after_an_unsent_prompt_is_reported_in_the_summary(retry_world: World) -> None:
    """Every earlier attempt stays visible: runs[], failures, inputs and the Markdown (INTEGRITY2-2)."""
    run_id = "pilot-demo-a:codex:1"
    redo(retry_world, run_id, publish_artifact=False, session=UNSENT, transcript=UNSENT_TRANSCRIPT)
    code, _out, err = run_main(retry_world, "run-prepare", run_id, *pilot_args(retry_world), "--retry", "crash (synthetic)")
    assert code == 0, err
    finish_retry(retry_world, run_id)
    summary = summarize(retry_world)
    run = run_of(summary, run_id)
    assert summary["decision"]["value"] == "go" and run["status"] == "completed" and run["invalidReasons"] == []
    failure = {"kind": "host-error", "detail": "the host crashed before the prompt (synthetic)"}
    assert run["priorAttempts"] == 1 and run["attempts"] == [
        {"attempt": 1, "status": "failed", "failure": failure, "promptSent": False, "sentBecause": None,
         "statuses": ["failed"]}]
    assert summary["failures"]["earlierAttempts"] == [
        {"id": run_id, "attempt": 1, "status": "failed", "failure": "host-error",
         "detail": "the host crashed before the prompt (synthetic)", "promptSent": False, "sentBecause": None}]
    earlier = retry_world.pilot / "evidence" / "pilot-demo-a.codex.1.attempt-1"
    entry = next(item for item in summary["inputs"]["runs"] if item["id"] == run_id)
    assert entry["earlierAttempts"] == [{"attempt": 1, "record": er.sha256_file(earlier / "record.json"), "review": None,
                                         "amendments": []}]
    markdown = wp.render_markdown(summary)
    assert f"Earlier attempts, kept and replaced by a retry: {run_id} attempt 1 {EM} failed (host-error: the host " \
           "crashed before the prompt (synthetic)); prompt never sent." in markdown
    review = (retry_world.evidence(run_id) / "review.md").read_bytes()
    assert entry["reviewNormalized"] == {"version": 1, "sha256": er.normalized_review_sha256(review)}
    assert f"- {run_id}: record {entry['record']}, review {entry['review']} (normalized v1 " \
           f"{entry['reviewNormalized']['sha256']}); attempt 1 record {er.sha256_file(earlier / 'record.json')}" in markdown
    planned = {item["id"]: item for item in wp.load_campaign(retry_world.root, CAMPAIGN).plan()}
    assert wp._sealed_inputs(wp._stage1_input_index(summary, planned)[run_id])[2] == (
        (1, er.sha256_file(earlier / "record.json"), ()),)


def test_an_earlier_attempt_is_verified_like_a_current_record(retry_world: World) -> None:
    """A one-field edit of an earlier attempt's record is refused by run-prepare --retry and by summarize (INTEGRITY2-3)."""
    run_id = "pilot-demo-b:claude-code:1"
    evidence = retry_world.evidence(run_id)
    redo(retry_world, run_id, publish_artifact=False, session=UNSENT, transcript=UNSENT_TRANSCRIPT)
    edit_json(evidence / "record.json", lambda value: value["session"].update(status="blocked"))
    code, _out, err = run_main(retry_world, "run-prepare", run_id, *pilot_args(retry_world), "--retry", "x (synthetic)")
    assert code == 1 and "does not verify against its sealed evidence (record.json session fields differ from " \
                         "session.md); a retry needs an intact sealed record" in err, err
    edit_json(evidence / "record.json", lambda value: value["session"].update(status="failed"))
    code, _out, err = run_main(retry_world, "run-prepare", run_id, *pilot_args(retry_world), "--retry", "x (synthetic)")
    assert code == 0, err
    finish_retry(retry_world, run_id)
    assert run_of(summarize(retry_world), run_id)["status"] == "completed"
    earlier = retry_world.pilot / "evidence" / "pilot-demo-b.claude-code.1.attempt-1"
    edit_json(earlier / "record.json", lambda value: value["session"].update(status="blocked"))
    problems = integrity_problems(retry_world)
    assert f"{run_id}: pilot-demo-b.claude-code.1.attempt-1: record.json session fields differ from session.md" in problems
    edit_json(earlier / "record.json", lambda value: value["session"].update(status="failed", priorAttempts=1))
    problems = integrity_problems(retry_world)
    assert f"{run_id}: pilot-demo-b.claude-code.1.attempt-1 says 1 prior attempt(s), not 0" in problems, problems


def test_a_hand_made_retry_after_a_sent_prompt_makes_the_run_invalid(retry_world: World,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """summarize applies the never-sent rule itself, so a retry made around run-prepare is caught (SPECDOCS2-1)."""
    run_id = "pilot-demo-b:codex:1"
    redo(retry_world, run_id, publish_artifact=False,
         session={"Status": "failed", "Failure": "repair-budget -- two repairs did not help (synthetic)"})
    with monkeypatch.context() as patched:
        patched.setattr(wp, "_prompt_sent", lambda chain, evidence=None: None)  # a retry prepared around the rule
        code, _out, err = run_main(retry_world, "run-prepare", run_id, *pilot_args(retry_world), "--retry", "x (synthetic)")
        assert code == 0, err
    finish_retry(retry_world, run_id)
    summary = summarize(retry_world)
    run = run_of(summary, run_id)
    assert run["status"] == "invalid" and summary["decision"]["value"] == "stop"
    assert run["invalidReasons"] == ["attempt 1 of this run sent the prompt (it failed with repair-budget); a retry is "
                                     "allowed only if the prompt was never sent (the policy's infrastructure retries); a "
                                     "failure after the prompt was sent is kept and counted"]
    assert summary["failures"]["earlierAttempts"][0]["failure"] == "repair-budget"


def test_a_recorded_stage1_summary_is_final(world: World) -> None:
    """A committed stop cannot be removed and replaced by a go (INTEGRITY2-1, P4)."""
    campaign_dir = world.root / wp.PILOT_REL / CAMPAIGN
    _set_review(world, "pilot-demo-a:codex:1", "demo-a-u01: stated coverage", "demo-a-u01: not-stated")
    code, _out, err = run_main(world, "summarize", *pilot_args(world), "--stage", "1", "--record")
    assert code == 0, err
    assert json.loads((campaign_dir / "stage1-summary.json").read_text(encoding="utf-8"))["decision"]["value"] == "stop"
    commit_files(world.root, {}, "synthetic stage 1 stop")
    git(world.root, "rm", "--quiet", f"{wp.PILOT_REL}/{CAMPAIGN}/stage1-summary.json",
        f"{wp.PILOT_REL}/{CAMPAIGN}/stage1-summary.md")
    git(world.root, "commit", "--quiet", "-m", "synthetic removal")
    _set_review(world, "pilot-demo-a:codex:1", "demo-a-u01: not-stated", "demo-a-u01: stated coverage")
    assert summarize(world)["decision"]["value"] == "go"
    code, _out, err = run_main(world, "summarize", *pilot_args(world), "--stage", "1", "--record")
    assert code == 1 and "stage1-summary.json was committed in " in err and "a recorded summary is final and is never " \
                                                                            "recorded again" in err, err
    assert not (campaign_dir / "stage1-summary.json").exists() and not (campaign_dir / "stage1-summary.md").exists()
    # A go written around summarize --record does not unlock Stage 2 either.
    summary = summarize(world)
    (campaign_dir / "stage1-summary.json").write_bytes(er.canonical_json(summary))
    (campaign_dir / "stage1-summary.md").write_bytes(wp.render_markdown(summary).encode("utf-8"))
    commit_files(world.root, {}, "synthetic go")
    code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(world))
    assert code == 1 and "the committed stage1-summary.json differs from the version first committed in " in err \
        and "(a recorded summary is final)" in err, err


def test_an_edited_stage1_go_does_not_unlock_stage_2(world: World) -> None:
    code, _out, err = run_main(world, "summarize", *pilot_args(world), "--stage", "1", "--record")
    assert code == 0, err
    commit_files(world.root, {}, "synthetic stage 1 go")
    path = world.root / wp.PILOT_REL / CAMPAIGN / "stage1-summary.json"
    path.write_bytes(path.read_bytes().replace(b'"note":', b'"note": ', 1))
    commit_files(world.root, {}, "synthetic edit")
    code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(world))
    assert code == 1 and "the committed stage1-summary.json differs from the version first committed in" in err, err


# --------------------------------------------------------------------------------------------
# Round 3: merges, retries and summaries (synthetic data only)


def test_a_recorded_stop_replaced_by_a_go_through_a_merge_does_not_unlock_stage_2(world: World) -> None:
    """A go recorded on a branch cut before the stop, merged with the conflict resolved to the go,
    leaves two contents in the history (INTEGRITY3-1)."""
    root = world.root
    rel = f"{wp.PILOT_REL}/{CAMPAIGN}"
    git(root, "branch", "side")
    _set_review(world, "pilot-demo-a:codex:1", "demo-a-u01: stated coverage", "demo-a-u01: not-stated")
    code, _out, err = run_main(world, "summarize", *pilot_args(world), "--stage", "1", "--record")
    assert code == 0, err
    commit_files(root, {}, "synthetic stage 1 stop")
    main = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    git(root, "checkout", "--quiet", "side")
    _set_review(world, "pilot-demo-a:codex:1", "demo-a-u01: not-stated", "demo-a-u01: stated coverage")
    code, _out, err = run_main(world, "summarize", *pilot_args(world), "--stage", "1", "--record")
    assert code == 0, err  # the side branch never saw the stop
    commit_files(root, {}, "synthetic stage 1 go on a side branch")
    git(root, "checkout", "--quiet", main)
    subprocess.run(["git", "-C", str(root), "merge", "--quiet", "--no-edit", "side"], capture_output=True, env=git_env(),
                   check=False)
    git(root, "checkout", "--theirs", "--", f"{rel}/stage1-summary.json", f"{rel}/stage1-summary.md")
    commit_files(root, {}, "synthetic merge resolved to the go")
    assert json.loads((root / rel / "stage1-summary.json").read_text(encoding="utf-8"))["decision"]["value"] == "go"
    code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(world))
    assert code == 1 and "(a recorded summary is final" in err, err
    assert "stage1-summary.json was committed with 2 different contents" in err or \
        "differs from the version first committed in" in err, err


def test_a_summary_removed_behind_a_merge_is_never_recorded_again(world: World) -> None:
    """record_summary reads the merge-aware history: a removal the default log hides still counts (INTEGRITY3-1)."""
    root = world.root
    main = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    git(root, "branch", "older")
    code, _out, err = run_main(world, "summarize", *pilot_args(world), "--stage", "1", "--record")
    assert code == 0, err
    commit_files(root, {}, "synthetic stage 1 go")
    git(root, "rm", "--quiet", f"{wp.PILOT_REL}/{CAMPAIGN}/stage1-summary.json",
        f"{wp.PILOT_REL}/{CAMPAIGN}/stage1-summary.md")
    git(root, "commit", "--quiet", "-m", "synthetic removal")
    git(root, "checkout", "--quiet", "older")
    commit_files(root, {"older.txt": b"synthetic\n"}, "synthetic older work")
    git(root, "merge", "--quiet", "--no-edit", main)
    git(root, "checkout", "--quiet", main)
    git(root, "merge", "--quiet", "--ff-only", "older")
    assert git(root, "log", "--format=%H", "--", f"{wp.PILOT_REL}/{CAMPAIGN}/stage1-summary.json") == ""
    code, _out, err = run_main(world, "summarize", *pilot_args(world), "--stage", "1", "--record")
    assert code == 1 and "a recorded summary is final and is never recorded again" in err, err



def test_prompt_sent_no_is_refused_against_the_workspace(retry_world: World) -> None:
    """A published artifact or a draft in the workspace shows the prompt reached the host, so run-finish
    refuses "Prompt sent: no" before writing anything (STATS3-1, INTEGRITY3-3)."""
    run_id = "pilot-demo-a:codex:1"
    forget(retry_world, run_id)
    assert run_main(retry_world, "run-prepare", run_id, *pilot_args(retry_world))[0] == 0
    workspace, evidence = retry_world.workspace(run_id), retry_world.evidence(run_id)
    (workspace / "draft.draft.json").write_text("{}", encoding="utf-8")
    (evidence / "session.md").write_text(session_text(run_id, **dict(UNSENT, Transcript="", **{"UI log": ""})),
                                         encoding="utf-8")
    before = sorted(path.name for path in evidence.iterdir())
    code, out, err = run_main(retry_world, "run-finish", run_id, *pilot_args(retry_world))
    assert code == 1 and "the skill wrote draft.draft.json in the workspace, so the prompt reached the host; write " \
                         '"Prompt sent: yes"' in err, out + err
    assert sorted(path.name for path in evidence.iterdir()) == before and workspace.is_dir()
    publish(workspace, "codex", "pilot-demo-a")
    code, out, err = run_main(retry_world, "run-finish", run_id, *pilot_args(retry_world))
    assert code == 1 and "pilot.mlview.json was published in the workspace, so the prompt reached the host" in err, err
    # Repair rounds above zero contradict "Prompt sent: no" in the session itself.
    (evidence / "session.md").write_text(session_text(run_id, **dict(UNSENT, **{"Repair rounds": "2"})),
                                         encoding="utf-8")
    messages = [p.message for p in wp.check_file(evidence / "session.md")]
    assert 'Repair rounds is 2, so the validator ran and the prompt was sent; write "Prompt sent: yes".' in messages


def test_prompt_sent_no_is_refused_against_sealed_evidence(retry_world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """An amendment cannot drop a sealed transcript or say "Prompt sent: no" beside a captured artifact,
    and a retry made around those rules is refused and counted invalid (INTEGRITY3-3, STATS3-1)."""
    run_id = "pilot-demo-b:codex:1"
    # Seal 1: failed, "Prompt sent:" left empty, the sealed transcript contains PROMPT.txt.
    redo(retry_world, run_id, publish_artifact=False,
         session={"Status": "failed", "Failure": "host-error -- the host crashed (synthetic)", "Repair rounds": "0"})
    evidence = retry_world.evidence(run_id)
    sealed_session = (evidence / "session.md").read_bytes()
    (evidence / "session.md").write_text(session_text(run_id, **dict(UNSENT, Transcript="")), encoding="utf-8")
    code, out, err = run_main(retry_world, "run-finish", run_id, *pilot_args(retry_world), "--amend", "x (synthetic)")
    assert code == 1 and "the transcript sealed earlier (transcript.txt, sha256 " in err, out + err
    (evidence / "session.md").write_bytes(sealed_session)
    # A seal that captured the published artifact (and no transcript) cannot be amended to "no".
    other = "pilot-demo-a:claude-code:1"
    redo(retry_world, other, publish_artifact=True, transcript="", session={
        "Status": "failed", "Failure": "host-error -- the host crashed (synthetic)", "Repair rounds": "0",
        "Transcript": ""})
    other_evidence = retry_world.evidence(other)
    record = json.loads((other_evidence / "record.json").read_text(encoding="utf-8"))
    assert record["evidence"]["partialArtifact"]["file"] == "partial-artifact.mlview.json"
    (other_evidence / "session.md").write_text(session_text(other, **dict(UNSENT, Transcript="")), encoding="utf-8")
    code, out, err = run_main(retry_world, "run-finish", other, *pilot_args(retry_world), "--amend", "x (synthetic)")
    assert code == 1 and 'this attempt cannot say "Prompt sent: no": it captured the published artifact ' \
                         "(partial-artifact.mlview.json)" in err, out + err
    # A record sealed around run-finish with "no" beside a captured artifact is not retried ...
    with monkeypatch.context() as patched:
        patched.setattr(wp, "_unsent_contradiction", lambda *args: None)
        redo(retry_world, other, publish_artifact=True, transcript="", session=dict(UNSENT, Transcript=""))
    code, _out, err = run_main(retry_world, "run-prepare", other, *pilot_args(retry_world), "--retry", "x (synthetic)")
    assert code == 1 and f"attempt 1 of {other} cannot be retried: it captured the published artifact " \
                         "(partial-artifact.mlview.json)" in err, err
    # ... and a retry prepared around that rule makes the run invalid, with the reason in the summary.
    with monkeypatch.context() as patched:
        patched.setattr(wp, "_prompt_sent", lambda chain, evidence=None: None)
        assert run_main(retry_world, "run-prepare", other, *pilot_args(retry_world), "--retry", "x (synthetic)")[0] == 0
    finish_retry(retry_world, other)
    summary = summarize(retry_world)
    run = run_of(summary, other)
    assert run["status"] == "invalid" and run["invalidReasons"][0].startswith(
        "attempt 1 of this run sent the prompt (it captured the published artifact (partial-artifact.mlview.json))")
    assert run["attempts"][0]["sentBecause"] == "it captured the published artifact (partial-artifact.mlview.json)"
    markdown = wp.render_markdown(summary)
    assert "prompt never sent" not in markdown
    assert f"{other} attempt 1 {EM} failed (host-error: the host crashed before the prompt (synthetic)); counted as " \
           "sent: it captured the published artifact (partial-artifact.mlview.json)" in markdown


def test_per_host_targets_name_the_failing_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A per-host miss names the host and does not print a pooled fraction that meets the threshold as
    the reason; the early-stop bound is repeated for each host (STATS3-4)."""
    world = build_world(tmp_path / "hosts", policy=make_policy(**{"scoring.perHostTargets": "yes"}))
    patches(monkeypatch, world)
    for run_id in stage1_ids():
        overrides = {("Essential facts", "demo-b-f02"): "missing"} if run_id == "pilot-demo-b:claude-code:1" else {}
        do_run(world, run_id, review_kwargs={"overrides": overrides})
    summary = summarize(world)
    assert summary["decision"]["value"] == "stop"
    assert summary["decision"]["reasons"] == [
        "T4 essentialFactRecall: pooled 7/8 meets it; within host claude-code 3/4 (needs >= 0.85)"]
    runs = [{"id": f"t{task}:{host}:1", "task": f"t{task}", "host": host, "status": status, "failure": None,
             "invalidReasons": [], "SV": int(status == "completed"), "E": 5 if status == "completed" else None,
             "X": 5 if status == "completed" else None, "errorCodes": [], "ess": 3 if reviewed else 0, "ESS": 10,
             "unk": int(reviewed), "UNK": 1, "fa": 0, "reviewed": reviewed,
             "reviewStatus": "complete" if reviewed else "missing",
             "claims": {"observed": {"supported": 10 if reviewed else 0, "qualified": 0, "unsupported": 0},
                        "inferred": {"supported": 0, "qualified": 0, "unsupported": 0}}}
            for task in range(8) for host in ("copilot", "codex", "claude-code")
            for status, reviewed in [("completed", True) if host == "codex" and task < 3 else ("pending", False)]]
    thresholds = {"structurallyValid": 1.0, "exactAnchors": 1.0, "supportedClaimPrecision": 0.95,
                  "essentialFactRecall": 0.85, "knownUnresolvedQualified": 1.0, "highSeverityFalseAccusations": 0}
    targets = wp.compute_targets(runs, thresholds, "not-supported", True, ["copilot", "codex", "claude-code"])
    indicators = wp._early_stop(runs, targets)
    assert "T4 (codex): at most 59/80 can still be reached" in indicators
    assert not any(item.startswith("T4: ") for item in indicators)


def test_a_pending_side_has_no_paired_difference(world: World) -> None:
    """A pending skill or baseline run shows no recall difference (STATS3-5)."""
    forget(world, "pilot-demo-a:codex:baseline:1")
    assert run_main(world, "run-prepare", "pilot-demo-a:codex:baseline:1", *pilot_args(world))[0] == 0
    forget(world, "pilot-demo-b:codex:1")
    assert run_main(world, "run-prepare", "pilot-demo-b:codex:1", *pilot_args(world))[0] == 0
    summary = summarize(world)
    rows = {(row["task"], row["host"]): row for row in summary["baselines"]["paired"]}
    assert rows[("pilot-demo-a", "codex")]["baseline"]["status"] == "pending"
    assert rows[("pilot-demo-a", "codex")]["recallDifference"] is None
    assert rows[("pilot-demo-b", "codex")]["skill"]["status"] == "pending"
    assert rows[("pilot-demo-b", "codex")]["recallDifference"] is None
    assert rows[("pilot-demo-a", "claude-code")]["recallDifference"] is not None
    markdown = wp.render_markdown(summary)
    assert "| pilot-demo-a | codex | 2/2 (completed) | 0/2 (pending) | n/a |" in markdown, markdown
    assert "a pending run, or a completed run that is not yet reviewed" in markdown


def test_baseline_entries_keep_their_reasons_and_earlier_attempts(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """An invalid baseline keeps its reasons, and a retried baseline's earlier attempt keeps its status
    and failure in the summary and the Markdown (STATS3-3, SPECDOCS3-1)."""
    world = build_world(tmp_path / "baselines", policy=make_policy(**{"budget.infrastructureRetries": 1}))
    patches(monkeypatch, world)
    retried = "pilot-demo-b:claude-code:baseline:1"
    for run_id in stage1_ids():
        if run_id == "pilot-demo-a:codex:baseline:1":
            do_run(world, run_id, session={"Active minutes": "35"})  # over the synthetic 20-minute budget
        elif run_id == retried:
            do_run(world, run_id, session=dict(UNSENT, **{"Repair rounds": ""}), transcript=UNSENT_TRANSCRIPT)
        else:
            do_run(world, run_id)
    assert run_main(world, "run-prepare", retried, *pilot_args(world), "--retry", "crash (synthetic)")[0] == 0
    evidence = world.evidence(retried)
    prompt = (evidence / "PROMPT.txt").read_text(encoding="utf-8")
    (evidence / "transcript.txt").write_text(prompt + "\nThe loop runs 40 steps.\n", encoding="utf-8")
    (evidence / "session.md").write_text(session_text(retried, **{"Prior attempts": "1"}), encoding="utf-8")
    assert run_main(world, "run-finish", retried, *pilot_args(world))[0] == 0
    assert run_main(world, "review-template", retried, *pilot_args(world))[0] == 0
    fill_review(evidence / "review.md")
    summary = summarize(world)
    runs = {run["id"]: run for run in summary["baselines"]["runs"]}
    invalid = runs["pilot-demo-a:codex:baseline:1"]
    assert invalid["status"] == "invalid" and any("exceed the budget" in reason for reason in invalid["invalidReasons"])
    failure = {"kind": "host-error", "detail": "the host crashed before the prompt (synthetic)"}
    assert runs[retried]["priorAttempts"] == 1 and runs[retried]["attempts"] == [
        {"attempt": 1, "status": "failed", "failure": failure, "promptSent": False, "sentBecause": None,
         "statuses": ["failed"]}]
    assert summary["baselines"]["earlierAttempts"] == [
        {"id": retried, "attempt": 1, "status": "failed", "failure": "host-error",
         "detail": "the host crashed before the prompt (synthetic)", "promptSent": False, "sentBecause": None}]
    assert summary["failures"]["earlierAttempts"] == []  # skill runs only
    markdown = wp.render_markdown(summary)
    assert "Baseline failures: pilot-demo-a:codex:baseline:1 — invalid [" in markdown and "exceed the budget" in markdown
    assert f"Baseline earlier attempts, kept and replaced by a retry: {retried} attempt 1 {EM} failed (host-error: the " \
           "host crashed before the prompt (synthetic)); prompt never sent." in markdown


def test_a_hand_edited_stage1_summary_does_not_unlock_stage_2(retry_world: World) -> None:
    """With the same tools, the whole committed Stage 1 summary must equal the re-computation and its
    Markdown the rendering of its JSON, so a retry cannot be hidden before the first commit (INTEGRITY3-4)."""
    run_id = "pilot-demo-a:codex:1"
    redo(retry_world, run_id, publish_artifact=False, session=UNSENT, transcript=UNSENT_TRANSCRIPT)
    assert run_main(retry_world, "run-prepare", run_id, *pilot_args(retry_world), "--retry", "crash (synthetic)")[0] == 0
    finish_retry(retry_world, run_id)
    directory = retry_world.root / wp.PILOT_REL / CAMPAIGN
    real = summarize(retry_world)
    assert real["decision"]["value"] == "go" and real["failures"]["earlierAttempts"]
    value = json.loads(er.canonical_json(real))
    markdown = wp.render_markdown(value)
    value["failures"]["earlierAttempts"] = []
    for run in value["runs"]:
        run["attempts"], run["priorAttempts"] = [], 0
    (directory / "stage1-summary.json").write_bytes(er.canonical_json(value))
    (directory / "stage1-summary.md").write_bytes(markdown.encode("utf-8"))
    commit_files(retry_world.root, {}, "synthetic go, retry disclosure removed from the JSON")
    code, _out, err = run_main(retry_world, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(retry_world))
    assert code == 1 and "the committed Stage 1 summary differs from a re-computation from the sealed evidence in " \
                         "failures, runs" in err, err
    git(retry_world.root, "reset", "--quiet", "--hard", "HEAD~1")
    value = json.loads(er.canonical_json(real))
    (directory / "stage1-summary.json").write_bytes(er.canonical_json(value))
    trimmed = "\n".join(line for line in markdown.splitlines() if not line.startswith("Earlier attempts")) + "\n"
    (directory / "stage1-summary.md").write_bytes(trimmed.encode("utf-8"))
    commit_files(retry_world.root, {}, "synthetic go, retry disclosure removed from the Markdown")
    code, _out, err = run_main(retry_world, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(retry_world))
    assert code == 1 and "the committed stage1-summary.md is not the Markdown rendered from stage1-summary.json" in err, err
    git(retry_world.root, "reset", "--quiet", "--hard", "HEAD~1")
    # A forged tooling field does not switch the comparison off (INTEGRITY4-3, STATS4-2).
    hidden = json.loads(er.canonical_json(real))
    hidden["failures"]["earlierAttempts"] = []
    for run in hidden["runs"]:
        run["attempts"], run["priorAttempts"] = [], 0
    for key, expected in (("tools/workflow_pilot.py", "the committed Stage 1 summary names a tools/workflow_pilot.py "
                                                      "(sha256 000000000000...) that is neither the running one nor any "
                                                      "version committed in the history of "),
                          ("tools/eval_records.py", "the committed Stage 1 summary names a tools/eval_records.py"),
                          ("skills/mlview/scripts/artifact.py", "the committed Stage 1 summary names a "
                                                                "skills/mlview/scripts/artifact.py that is not the "
                                                                "candidate's frozen helper")):
        forged = json.loads(er.canonical_json(hidden))
        forged["tooling"][key] = "0" * 64
        (directory / "stage1-summary.json").write_bytes(er.canonical_json(forged))
        (directory / "stage1-summary.md").write_bytes(wp.render_markdown(forged).encode("utf-8"))
        commit_files(retry_world.root, {}, f"synthetic go, retry hidden, forged {key}")
        code, _out, err = run_main(retry_world, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(retry_world))
        assert code == 1 and expected in err, err
        git(retry_world.root, "reset", "--quiet", "--hard", "HEAD~1")
    # The bytes summarize --record writes (this synthetic world plans baselines it never ran).
    (directory / "stage1-summary.json").write_bytes(er.canonical_json(real))
    (directory / "stage1-summary.md").write_bytes(markdown.encode("utf-8"))
    commit_files(retry_world.root, {}, "synthetic go as summarize --record writes it")
    code, _out, err = run_main(retry_world, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(retry_world))
    assert code == 0, err


def test_a_stage1_summary_recorded_with_other_committed_tools_still_discloses_retries(retry_world: World) -> None:
    """A summary recorded with other tools, bound by Git (the tool committed with the summary), unlocks
    Stage 2 with a note, but only while its run statuses, failures and earlier attempts equal the
    re-computation (INTEGRITY4-3, STATS4-2)."""
    run_id = "pilot-demo-a:codex:1"
    redo(retry_world, run_id, publish_artifact=False, session=UNSENT, transcript=UNSENT_TRANSCRIPT)
    assert run_main(retry_world, "run-prepare", run_id, *pilot_args(retry_world), "--retry", "crash (synthetic)")[0] == 0
    finish_retry(retry_world, run_id)
    directory = retry_world.root / wp.PILOT_REL / CAMPAIGN
    old_tool = b"# an older synthetic tools/workflow_pilot.py\n"
    real = json.loads(er.canonical_json(summarize(retry_world)))
    real["tooling"]["tools/workflow_pilot.py"] = sha(old_tool)
    real["perTask"] = "a field that another tool version shaped differently (synthetic)"
    for hide in (True, False):
        value = json.loads(er.canonical_json(real))
        if hide:
            value["failures"]["earlierAttempts"] = []
            for run in value["runs"]:
                run["attempts"], run["priorAttempts"] = [], 0
        commit_files(retry_world.root, {f"{wp.PILOT_REL}/{CAMPAIGN}/stage1-summary.json": er.canonical_json(value),
                                        f"{wp.PILOT_REL}/{CAMPAIGN}/stage1-summary.md": b"# rendered by the older tool\n",
                                        "tools/workflow_pilot.py": old_tool}, "synthetic summary with its tools")
        code, out, err = run_main(retry_world, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(retry_world))
        if hide:
            assert code == 1 and "the committed Stage 1 summary misstates the runs' statuses, failures or earlier " \
                                 "attempts (failures.earlierAttempts, runs)" in err, err
            git(retry_world.root, "reset", "--quiet", "--hard", "HEAD~1")
        else:
            assert code == 0, err
            assert "Note: the committed Stage 1 summary was recorded with other tools (versions committed in its " \
                   "history); its decision, its sealed inputs, its normalized review hashes and the failures and " \
                   "earlier attempts of its skill runs and baselines were compared with a re-computation" in out, out
    assert (directory / "stage1-summary.json").is_file()


def test_summarize_record_refuses_uncommitted_tools_in_the_checkout(world: World,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """A summary is recorded only with the tools committed at HEAD, which the Stage 2 gate and check-frozen
    read back from Git (INTEGRITY4-3)."""
    summary = summarize(world)
    assert wp._uncommitted_tools(world.root, summary) == []  # a test world outside the checkout
    monkeypatch.setattr(wp, "ROOT", world.root)
    assert wp._uncommitted_tools(world.root, summary) == list(wp.TOOL_KEYS)
    with pytest.raises(wp.PilotError, match=r"differ\(s\) from the version committed at HEAD; commit or discard"):
        wp.record_summary(world.root, summary)
    commit_files(world.root, {key: (ROOT / key).read_bytes() for key in wp.TOOL_KEYS}, "synthetic copy of the tools")
    assert wp._uncommitted_tools(world.root, summary) == []


def skill_draft(run_id: str):
    """A before_finish hook that writes the draft where SKILL.md puts it: .mlview/llm/<run-id>/draft.json."""
    task, host = run_id.split(":")[:2]

    def write(workspace: Path, _evidence: Path) -> None:
        target = workspace / ".mlview" / "llm" / er.run_dir_name(run_id) / "draft.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(draft_for(task, host)), encoding="utf-8")
    return write


def test_a_skill_draft_under_dot_mlview_shows_the_prompt_was_sent(retry_world: World,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """The draft SKILL.md writes (.mlview/llm/<run-id>/draft.json) counts as skill output: run-finish, --amend
    and run-prepare --retry refuse "Prompt sent: no", and summarize counts such an earlier attempt as sent
    (INTEGRITY4-2, STATS4-1, SPECDOCS4-1)."""
    assert wp._outputs_added({"README.md": "x", ".claude/skills/mlview/SKILL.md": "x"}, {
        "README.md": "x", ".claude/skills/mlview/SKILL.md": "x", ".claude/skills/mlview/scripts/new.py": "x",
        ".claude/settings.local.json": "x", ".mlview/llm/run/draft.json": "x", ".MLVIEW/llm/run/node.json": "x",
        "notes.txt": "x", "sub/a.draft.json": "x"}) == [".MLVIEW/llm/run/node.json", ".mlview/llm/run/draft.json",
                                                         "sub/a.draft.json"]
    run_id = "pilot-demo-a:codex:1"
    draft = f".mlview/llm/{er.run_dir_name(run_id)}/draft.json"
    why = f"the skill wrote {draft} in the workspace, so the prompt reached the host"
    forget(retry_world, run_id)
    assert run_main(retry_world, "run-prepare", run_id, *pilot_args(retry_world))[0] == 0
    workspace, evidence = retry_world.workspace(run_id), retry_world.evidence(run_id)
    skill_draft(run_id)(workspace, evidence)
    (evidence / "session.md").write_text(session_text(run_id, **dict(UNSENT, Transcript="", **{"UI log": ""})),
                                         encoding="utf-8")
    before = sorted(path.name for path in evidence.iterdir())
    code, out, err = run_main(retry_world, "run-finish", run_id, *pilot_args(retry_world))
    assert code == 1 and why in err, out + err
    assert sorted(path.name for path in evidence.iterdir()) == before and workspace.is_dir()
    shutil.rmtree(workspace)  # fixture setup only: start this run again
    # A seal with "Prompt sent:" left empty cannot be amended to "no" beside the sealed draft.
    redo(retry_world, run_id, publish_artifact=False, before_finish=skill_draft(run_id), transcript=UNSENT_TRANSCRIPT,
         session={"Status": "failed", "Failure": "host-error -- the host crashed (synthetic)", "Repair rounds": "0"})
    (evidence / "session.md").write_text(session_text(run_id, **dict(UNSENT)), encoding="utf-8")
    code, out, err = run_main(retry_world, "run-finish", run_id, *pilot_args(retry_world), "--amend", "x (synthetic)")
    assert code == 1 and f'this attempt cannot say "Prompt sent: no": the skill wrote {draft} in its workspace' in err, \
        out + err
    # A record sealed around run-finish with "no" beside the draft is not retried ...
    with monkeypatch.context() as patched:
        patched.setattr(wp, "_unsent_contradiction", lambda *args: None)
        redo(retry_world, run_id, publish_artifact=False, before_finish=skill_draft(run_id), session=UNSENT,
             transcript=UNSENT_TRANSCRIPT)
    code, _out, err = run_main(retry_world, "run-prepare", run_id, *pilot_args(retry_world), "--retry", "x (synthetic)")
    assert code == 1 and f"attempt 1 of {run_id} cannot be retried: the skill wrote {draft} in its workspace" in err, err
    # ... and a retry prepared around that rule makes the run invalid, with the reason in the summary.
    with monkeypatch.context() as patched:
        patched.setattr(wp, "_prompt_sent", lambda chain, evidence=None: None)
        assert run_main(retry_world, "run-prepare", run_id, *pilot_args(retry_world), "--retry", "x (synthetic)")[0] == 0
    finish_retry(retry_world, run_id)
    run = run_of(summarize(retry_world), run_id)
    assert run["status"] == "invalid" and run["attempts"][0]["sentBecause"] == f"the skill wrote {draft} in its workspace"


def test_summary_markdown_is_written_as_bytes_in_the_tests() -> None:
    """The code compares a summary's Markdown byte for byte with LF output, and Path.write_text writes CRLF
    on Windows, so the tests write summary Markdown as bytes (DISTCI4-1)."""
    pattern = re.compile(r"summary\.md[\"')]*\)\.write_text\(")
    offenders = [f"{path.name}:{number}" for path in sorted((ROOT / "evals" / "workflow").glob("test_*.py"))
                 + sorted((ROOT / "tools").glob("test_*.py"))
                 for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if pattern.search(line)]
    assert offenders == []


def test_check_frozen_renders_the_markdown_only_with_the_same_tool(world: World, tmp_path: Path) -> None:
    """check-frozen compares a recorded summary's Markdown with the rendering of its JSON while the
    summary names the running tools/workflow_pilot.py; otherwise it notes the check (INTEGRITY3-4)."""
    import workflow_decisions as wd  # noqa: PLC0415

    value = json.loads(er.canonical_json(summarize(world)))
    directory = tmp_path / "pilot-99"
    directory.mkdir()
    (directory / "stage1-summary.md").write_bytes(wp.render_markdown(value).encode("utf-8"))
    problems: list[str] = []
    notes: list[str] = []
    wd._rendering_check(value, directory, "stage1-summary.json", "stage1-summary.md", "pilot-99", problems, notes)
    assert problems == [] and notes == []
    (directory / "stage1-summary.md").write_bytes(
        wp.render_markdown(value).replace("Failures: none.\n", "").encode("utf-8"))
    wd._rendering_check(value, directory, "stage1-summary.json", "stage1-summary.md", "pilot-99", problems, notes)
    assert problems == ["pilot-99/stage1-summary.md is not the Markdown rendered from stage1-summary.json (a recorded "
                        "summary is written only by summarize --record)"]
    value["tooling"]["tools/workflow_pilot.py"] = "0" * 64
    problems.clear()
    wd._rendering_check(value, directory, "stage1-summary.json", "stage1-summary.md", "pilot-99", problems, notes)
    assert problems == [] and notes == ["check-frozen: pilot-99: not verified: stage1-summary.md rendered from "
                                        "stage1-summary.json (it names another tools/workflow_pilot.py, and no commit "
                                        "that recorded it can be read)."]


def test_check_frozen_skips_the_rendering_only_for_the_tool_committed_with_the_summary(world: World,
                                                                                       tmp_path: Path) -> None:
    """The summary's tooling field never switches the rendering check off on its own word: another
    tools/workflow_pilot.py is accepted (as a note) only when it is the one committed with the summary
    (INTEGRITY4-3)."""
    import workflow_decisions as wd  # noqa: PLC0415

    value = json.loads(er.canonical_json(summarize(world)))
    old_tool = b"# an older synthetic tools/workflow_pilot.py\n"
    repo = tmp_path / "repo"
    directory = repo / wp.PILOT_REL / "pilot-99"
    value["tooling"]["tools/workflow_pilot.py"] = sha(old_tool)
    commit_files(repo, {f"{wp.PILOT_REL}/pilot-99/stage1-summary.json": er.canonical_json(value),
                        f"{wp.PILOT_REL}/pilot-99/stage1-summary.md": b"# not the rendering (synthetic)\n",
                        "tools/workflow_pilot.py": old_tool})
    first = git(repo, "rev-parse", "HEAD")

    def checked(tooling: str) -> tuple[list[str], list[str]]:
        value["tooling"]["tools/workflow_pilot.py"] = tooling
        problems: list[str] = []
        notes: list[str] = []
        history = wd.History(wd.World(repo, None))
        wd._rendering_check(value, directory, "stage1-summary.json", "stage1-summary.md", "pilot-99", problems, notes,
                            history)
        return problems, notes

    assert checked(sha(old_tool)) == ([], [
        "check-frozen: pilot-99: not verified: stage1-summary.md rendered from stage1-summary.json (it was recorded with "
        f"the tools/workflow_pilot.py committed in {first[:12]}, not the running one)."])
    assert checked("0" * 64) == ([
        "pilot-99/stage1-summary.json names a tools/workflow_pilot.py (sha256 000000000000...) that is neither the "
        f"running one nor any version committed in the history of {first[:12]}, the commit that recorded it (a recorded "
        "summary is written only by summarize --record, with the tools committed at HEAD; a rebase that rewrote the "
        "commit holding those tools also causes this). Next: if the summary commit is not pushed, drop it, delete both "
        "summary files and record again; otherwise the owner writes invalidation.md and a new campaign supersedes this "
        "one (evals/workflow/pilot/README.md)"], [])


# --------------------------------------------------------------------------------------------
# Round 5: tool binding through Git history, baseline disclosure, final Stage 1 evidence (synthetic)


OLD_TOOL = b"# the synthetic tools/workflow_pilot.py committed at HEAD when summarize --record ran\n"


def summary_files(summary: dict) -> dict[str, bytes]:
    return {f"{wp.PILOT_REL}/{CAMPAIGN}/stage1-summary.json": er.canonical_json(summary),
            f"{wp.PILOT_REL}/{CAMPAIGN}/stage1-summary.md": wp.render_markdown(summary).encode("utf-8")}


@pytest.mark.parametrize("order", ["pull-before-commit", "commit-with-tool-change", "rebase-after-commit",
                                   "commit-then-pull"])
def test_an_honest_summary_stays_bound_when_the_tools_change_around_its_commit(world: World, order: str) -> None:
    """summarize --record writes the tools committed at HEAD; a pull, a rebase or a tool commit between the
    record and the summary's commit keeps that HEAD in the summary's history, so the Stage 2 gate and
    check-frozen accept the summary with a note (INTEGRITY5-1, DISTCI5-1, SPECDOCS5-1)."""
    import workflow_decisions as wd  # noqa: PLC0415

    root = world.root
    real = json.loads(er.canonical_json(summarize(world)))
    assert real["decision"]["value"] == "go"
    real["tooling"]["tools/workflow_pilot.py"] = sha(OLD_TOOL)
    running = (ROOT / "tools" / "workflow_pilot.py").read_bytes()
    commit_files(root, {"tools/workflow_pilot.py": OLD_TOOL}, "synthetic: the tools when summarize --record ran")
    if order == "pull-before-commit":
        commit_files(root, {"tools/workflow_pilot.py": running}, "synthetic: a pulled tool update")
        commit_files(root, summary_files(real), "synthetic: the recorded summary")
    elif order == "commit-with-tool-change":
        commit_files(root, {**summary_files(real), "tools/workflow_pilot.py": running},
                     "synthetic: git commit -a with a tool edit")
    elif order == "rebase-after-commit":
        branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
        git(root, "checkout", "--quiet", "-b", "upstream")
        commit_files(root, {"tools/workflow_pilot.py": running}, "synthetic: an upstream tool update")
        git(root, "checkout", "--quiet", branch)
        commit_files(root, summary_files(real), "synthetic: the recorded summary")
        git(root, "rebase", "--quiet", "upstream")  # git pull --rebase
    else:
        commit_files(root, summary_files(real), "synthetic: the recorded summary")
        commit_files(root, {"tools/workflow_pilot.py": running}, "synthetic: a later tool update")
    code, out, err = run_main(world, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(world))
    assert code == 0, err
    assert "Note: the committed Stage 1 summary was recorded with other tools (versions committed in its history)" \
        in out, out
    problems: list[str] = []
    notes: list[str] = []
    wd._rendering_check(real, root / wp.PILOT_REL / CAMPAIGN, "stage1-summary.json", "stage1-summary.md", CAMPAIGN,
                        problems, notes, wd.History(wd.World(root, None)))
    assert problems == [] and len(notes) == 1 and "it was recorded with the tools/workflow_pilot.py committed in " \
        in notes[0], (problems, notes)


def unsent_baseline_world(base: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    """Every Stage 1 run sealed and reviewed under a synthetic one-retry policy (no human agreed to it), with the
    baseline RETRIED failed before the prompt was sent; Stage 1 is go and its baselines are complete."""
    world = build_world(base, policy=make_policy(**{"budget.infrastructureRetries": 1}))
    patches(monkeypatch, world)
    for run_id in stage1_ids():
        if run_id == RETRIED:
            do_run(world, run_id, session=dict(UNSENT, **{"Repair rounds": ""}), transcript=UNSENT_TRANSCRIPT)
        else:
            do_run(world, run_id)
    return world


RETRIED = "pilot-demo-b:claude-code:baseline:1"


def retry_baseline(world: World) -> None:
    """Retry RETRIED through run-prepare and seal and review the new attempt (synthetic)."""
    assert run_main(world, "run-prepare", RETRIED, *pilot_args(world), "--retry", "crash (synthetic)")[0] == 0
    evidence = world.evidence(RETRIED)
    prompt = (evidence / "PROMPT.txt").read_text(encoding="utf-8")
    (evidence / "transcript.txt").write_text(prompt + "\nThe loop runs 40 steps.\n", encoding="utf-8")
    (evidence / "session.md").write_text(session_text(RETRIED, **{"Prior attempts": "1"}), encoding="utf-8")
    assert run_main(world, "run-finish", RETRIED, *pilot_args(world))[0] == 0
    assert run_main(world, "review-template", RETRIED, *pilot_args(world))[0] == 0
    fill_review(evidence / "review.md")


def test_a_summary_recorded_with_other_tools_must_disclose_the_baselines(tmp_path: Path,
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """With other committed tools, the baselines' statuses, failures and earlier attempts are compared with the
    re-computation too, as the note says (INTEGRITY5-2, STATS5-3)."""
    world = unsent_baseline_world(tmp_path / "w", monkeypatch)
    retry_baseline(world)
    real = json.loads(er.canonical_json(summarize(world)))
    assert real["decision"]["value"] == "go" and real["baselines"]["complete"] is True
    assert len(real["baselines"]["earlierAttempts"]) == 1
    real["tooling"]["tools/workflow_pilot.py"] = sha(OLD_TOOL)
    commit_files(world.root, {"tools/workflow_pilot.py": OLD_TOOL}, "synthetic: the tools when recorded")
    hidden = json.loads(er.canonical_json(real))
    for run in hidden["baselines"]["runs"]:
        if run["id"] == RETRIED:
            run.update(priorAttempts=0, attempts=[])
    hidden["baselines"]["earlierAttempts"] = []
    for forged, keys in ((hidden, "baselines.earlierAttempts, baselines.runs"),):
        commit_files(world.root, summary_files(forged), "synthetic: a summary with its baselines misstated")
        code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(world))
        assert code == 1 and f"misstates the runs' statuses, failures or earlier attempts ({keys})" in err, err
        git(world.root, "reset", "--quiet", "--hard", "HEAD~1")
    commit_files(world.root, summary_files(real), "synthetic: the summary as recorded")
    code, out, err = run_main(world, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(world))
    assert code == 0 and "its normalized review hashes and the failures and earlier attempts of its skill runs and " \
                         "baselines were compared" in out, out + err


def test_stage1_runs_are_final_once_the_stage1_summary_is_recorded(tmp_path: Path,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """--record refuses while a retry the policy permits is open (INTEGRITY-F3, STATS-F1); once the Stage 1
    summary is recorded, a retry or an amendment of a Stage 1 run is refused before any other advice, and an
    edit made for the refused amendment is named with its undo (STATS5-1, INTEGRITY-F2, STATS-F4)."""
    world = unsent_baseline_world(tmp_path / "w", monkeypatch)
    summary = summarize(world)
    assert summary["decision"]["value"] == "go"
    command = f'python tools/workflow_eval.py run-prepare {RETRIED} --campaign {CAMPAIGN} --retry "<reason>"'
    assert summary["openRetries"] == [{"id": RETRIED, "attempt": 1, "command": command}]
    assert f"- {RETRIED} attempt 1: {command}" in wp.render_markdown(summary)
    code, _out, err = run_main(world, "summarize", *pilot_args(world), "--stage", "1", "--record")
    assert code == 1 and f"a failure the run policy lets you retry is still open (attempt 1 of {RETRIED}: {command}); " \
                         "retry it before recording" in err, err
    assert not (world.root / wp.PILOT_REL / CAMPAIGN / "stage1-summary.json").exists()
    retry_baseline(world)
    code, _out, err = run_main(world, "summarize", *pilot_args(world), "--stage", "1", "--record")
    assert code == 0 and "Stage 1 runs can no longer be retried or amended" in err, err
    assert "Commit both files now, in one commit, before any other commit, pull, merge or rebase" in err, err
    code, _out, err = run_main(world, "run-prepare", RETRIED, *pilot_args(world), "--retry", "crash (synthetic)")
    assert code == 1 and f"{RETRIED} cannot be retried: the Stage 1 summary is recorded (evals/workflow/pilot/" \
                         f"{CAMPAIGN}/stage1-summary.json exists). Stage 1 evidence is final" in err, err
    commit_files(world.root, {}, "synthetic stage 1 go")
    skill = "pilot-demo-b:codex:1"
    session = world.evidence(skill) / "session.md"
    sealed = session.read_bytes()
    session.write_text(session_text(skill, **{"Active minutes": "12"}), encoding="utf-8")
    code, _out, err = run_main(world, "run-finish", skill, *pilot_args(world), "--amend", "typo (synthetic)")
    assert code == 1 and f"{skill} cannot be amended: the Stage 1 summary is recorded" in err, err
    assert "session.md no longer has its sealed bytes (sha256 " in err and "undo your edit exactly" in err, err
    code, _out, err = run_main(world, "run-finish", skill, *pilot_args(world))
    assert code == 1 and f"{skill} is already sealed, and the Stage 1 summary is recorded" in err, err
    code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(world))
    assert code == 1 and "the campaign evidence has 1 integrity problem(s), for example pilot-demo-b:codex:1: " \
                         "session: session.md does not match its sealed SHA-256" in err, err
    session.write_bytes(sealed)
    code, _out, err = run_main(world, "run-finish", skill, *pilot_args(world), "--amend", "typo (synthetic)")
    assert code == 1 and "cannot be amended" in err and "no longer has its sealed bytes" not in err, err
    assert run_main(world, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(world))[0] == 0
    git(world.root, "rm", "--quiet", f"{wp.PILOT_REL}/{CAMPAIGN}/stage1-summary.json",
        f"{wp.PILOT_REL}/{CAMPAIGN}/stage1-summary.md")
    commit_files(world.root, {}, "synthetic removal (a recorded summary stays recorded in the history)")
    code, _out, err = run_main(world, "run-prepare", RETRIED, *pilot_args(world), "--retry", "crash (synthetic)")
    assert code == 1 and f"stage1-summary.json was committed in " in err, err
    code, out, err = run_main(world, "run-prepare", "pilot-demo-a:codex:3", *pilot_args(world))
    assert code == 1  # the removed summary no longer unlocks Stage 2 either


def test_an_absent_corpus_leaves_stage_2_runs_valid_in_the_all_stage_summary(world: World) -> None:
    """A Stage 1 re-computation that is incomplete only because the corpus is absent here does not make the
    Stage 2 runs protocol-invalid: the all-stage summary is incomplete with a note (STATS5-2, section 4.5 E)."""
    code, _out, err = run_main(world, "summarize", *pilot_args(world), "--stage", "1", "--record")
    assert code == 0, err
    commit_files(world.root, {}, "synthetic stage 1 go")
    later = {"Started": "2026-10-25T09:00:00Z", "Ended": "2026-10-25T09:15:00Z"}
    for run_id in [f"{task}:{host}:{rep}" for task, _repo, _entry in TASKS for host in HOSTS for rep in (2, 3)]:
        do_run(world, run_id, session=later)
    assert summarize(world, "all")["decision"]["value"] == "targets-met"
    shutil.move(str(world.corpus / "demo-b"), str(world.base / "demo-b-away"))
    summary = summarize(world, "all")
    assert summary["decision"]["value"] == "incomplete"
    assert [run["id"] for run in summary["runs"] if run["status"] == "invalid"] == []
    assert not [line for line in summary["decision"]["earlyStopIndicators"] if line.startswith("T1:")]
    assert any(note.startswith("the committed Stage 1 go could not be re-verified: a re-computation of Stage 1 cannot "
                               "verify the artifacts here (corpus absent or unverified)")
               for note in summary["verification"]["notes"]), summary["verification"]["notes"]
    campaign = wp.load_campaign(world.root, CAMPAIGN)
    stage1 = wp._committed_stage1(world.root, campaign)
    assert isinstance(wp._stage1_matches(world.root, campaign, str(world.pilot), stage1), wp.Stage1Unverified)
    # A re-saved review (CRLF, a note) changes nothing either way; with the corpus back, the go is re-verified.
    review = world.evidence("pilot-demo-b:codex:1") / "review.md"
    review.write_bytes(review.read_bytes().replace(b"\n", b"\r\n") + b"> a note added later (synthetic)\r\n")
    summary = summarize(world, "all")
    assert summary["decision"]["value"] == "incomplete" and not [r for r in summary["runs"] if r["status"] == "invalid"]
    shutil.move(str(world.base / "demo-b-away"), str(world.corpus / "demo-b"))
    assert summarize(world, "all")["decision"]["value"] == "targets-met"
    # A Stage 1 record that differs from the summary's inputs holds the all-stage summary too, named.
    record = world.evidence("pilot-demo-a:codex:1") / "record.json"
    record.write_bytes(record.read_bytes().replace(b'"amendments": []', b'"amendments": [ ]', 1))
    summary = summarize(world, "all")
    assert summary["decision"]["value"] == "incomplete" and not [r for r in summary["runs"] if r["status"] == "invalid"]
    assert any("pilot-demo-a:codex:1: record.json sha256" in note for note in summary["verification"]["notes"]), \
        summary["verification"]["notes"]


def test_an_earlier_attempt_that_completed_is_never_shown_as_unsent(tmp_path: Path,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """A completed baseline amended to failed with "Prompt sent: no" and then retried around run-prepare is
    invalid, and the summary says why the attempt counts as sent instead of "prompt never sent" (STATS5-4)."""
    world = build_world(tmp_path / "w", policy=make_policy(**{"budget.infrastructureRetries": 1}))
    patches(monkeypatch, world)
    base = "pilot-demo-a:codex:baseline:1"
    answer = "The loop runs 40 steps.\nIt updates data.\nThe data origin is unknown.\n"
    for run_id in stage1_ids():
        if run_id == base:
            do_run(world, run_id, transcript=answer, review=False)
        else:
            do_run(world, run_id)
    evidence = world.evidence(base)
    (evidence / "session.md").write_text(session_text(base, **dict(UNSENT, **{"Repair rounds": ""})), encoding="utf-8")
    assert run_main(world, "run-finish", base, *pilot_args(world), "--amend", "the answer was lost (synthetic)")[0] == 0
    code, _out, err = run_main(world, "run-prepare", base, *pilot_args(world), "--retry", "x (synthetic)")
    assert code == 1 and "completed before it was amended; a completed run is never retried" in err, err
    with monkeypatch.context() as patched:
        patched.setattr(wp, "_seal_status", lambda seal: "failed")  # a retry prepared around the rule
        assert run_main(world, "run-prepare", base, *pilot_args(world), "--retry", "x (synthetic)")[0] == 0
    prompt = (evidence / "PROMPT.txt").read_text(encoding="utf-8")
    (evidence / "transcript.txt").write_text(prompt + "\n" + answer, encoding="utf-8")
    (evidence / "session.md").write_text(session_text(base, **{"Prior attempts": "1"}), encoding="utf-8")
    assert run_main(world, "run-finish", base, *pilot_args(world))[0] == 0
    assert run_main(world, "review-template", base, *pilot_args(world))[0] == 0
    fill_review(evidence / "review.md")
    summary = summarize(world)
    run = next(item for item in summary["baselines"]["runs"] if item["id"] == base)
    assert run["status"] == "invalid" and run["attempts"][0]["sentBecause"] == "it completed before it was amended"
    markdown = wp.render_markdown(summary)
    line = next(item for item in markdown.splitlines() if item.startswith("Baseline earlier attempts"))
    assert "prompt never sent" not in line and "counted as sent: it completed before it was amended" in line, line


# --------------------------------------------------------------------------------------------
# Final round: honest-path fixes (synthetic data only)


@pytest.mark.parametrize("rule", ["review", "protocol"])
def test_a_later_tool_rule_for_a_baseline_leaves_an_honest_go_in_force(world: World, monkeypatch: pytest.MonkeyPatch,
                                                                       rule: str) -> None:
    """A Stage 1 summary recorded with other (Git-bound) tools is compared on sealed facts: a later tool version
    that judges one baseline differently (a new review or protocol rule) neither blocks Stage 2 nor makes the
    Stage 2 runs invalid, and the all-stage summary can be recorded (INTEGRITY-F1)."""
    root = world.root
    real = json.loads(er.canonical_json(summarize(world)))
    assert real["decision"]["value"] == "go" and real["baselines"]["complete"] is True
    real["tooling"]["tools/workflow_pilot.py"] = sha(OLD_TOOL)
    commit_files(root, {"tools/workflow_pilot.py": OLD_TOOL}, "synthetic: the tools when summarize --record ran")
    commit_files(root, summary_files(real), "synthetic: the recorded summary")
    base = "pilot-demo-a:codex:baseline:1"
    if rule == "review":
        earlier_review = wp.check_review

        def later_review(record, display, ctx):
            problems, data = earlier_review(record, display, ctx)
            if ctx.run_id == base:
                problems = problems + [er.Problem(display, 1, er.ERROR, "Task", "a later synthetic review rule")]
            return problems, data
        monkeypatch.setattr(wp, "check_review", later_review)
    else:
        earlier_protocol = wp._protocol

        def later_protocol(state, campaign, stage1, stage1_problem=None):
            earlier_protocol(state, campaign, stage1, stage1_problem)
            if state.run["id"] == base:
                state.invalid.append("a later synthetic protocol rule")
        monkeypatch.setattr(wp, "_protocol", later_protocol)
    later = summarize(world)
    assert later["decision"]["value"] == "go"
    assert next(r for r in later["baselines"]["runs"] if r["id"] == base)["status"] != "completed" \
        or later["baselines"]["reviewProblems"] == [base]
    code, out, err = run_main(world, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(world))
    assert code == 0 and "recorded with other tools" in out, err
    shutil.rmtree(world.workspace("pilot-demo-a:codex:2"))  # fixture setup only: do_run prepares it again
    forget(world, "pilot-demo-a:codex:2")
    after = {"Started": "2026-10-25T09:00:00Z", "Ended": "2026-10-25T09:15:00Z"}
    for run_id in [f"{task}:{host}:{rep}" for task, _repo, _entry in TASKS for host in HOSTS for rep in (2, 3)]:
        do_run(world, run_id, session=after)
    summary = summarize(world, "all")
    assert summary["decision"]["value"] == "targets-met", summary["decision"]
    assert not [run["id"] for run in summary["runs"] if run["status"] == "invalid"]
    code, _out, err = run_main(world, "summarize", *pilot_args(world), "--stage", "all", "--record")
    assert code == 0, err


# --------------------------------------------------------------------------------------------
# Normalized review hashes (review normalization v1): the Stage 1 gate compares, for every Stage 1
# review the recorded summary lists, the hash of the review without what the grammar ignores,
# whichever tools recorded the summary (synthetic data only)


LATER = {"Started": "2026-10-25T09:00:00Z", "Ended": "2026-10-25T09:10:00Z"}
ACCUSATIONS = '"response:40-42: high | medium | low" for each false accusation in the answer.\n'
HELD = "the committed Stage 1 go is not re-verified here (see the verification notes)"
RESTORE = ("only '>' notes, line endings, trailing spaces and blank lines may change; restore everything else in each "
           "named review.md exactly as it was when the summary was recorded")


def _each_line(raw: bytes, change) -> bytes:
    """``raw`` (LF lines) with ``change(line) -> [lines]`` applied to every line."""
    out: list[str] = []
    for line in raw.decode("utf-8").split("\n"):
        out.extend(change(line))
    return "\n".join(out).encode("utf-8")


def _note_edited(line: str) -> list[str]:
    return ["  > Written by review-template; this note was edited after the record (synthetic)"] \
        if line.startswith("> Written by review-template") else [line]


# What an editor, or a reviewer adding notes, may do to a recorded Stage 1 review.md (synthetic): every
# other character stays as it was.
HONEST_EDITS = {
    "crlf": lambda raw: raw.replace(b"\n", b"\r\n"),
    "cr": lambda raw: raw.replace(b"\n", b"\r"),
    "bom": lambda raw: b"\xef\xbb\xbf" + raw,
    "note-added": lambda raw: _each_line(raw, lambda line: [line, "\t> a note added after the record (synthetic)"]
                                         if line.startswith("## ") else [line]) + b"> a closing note (synthetic)\n",
    "note-edited": lambda raw: _each_line(raw, _note_edited),
    "note-removed": lambda raw: _each_line(raw, lambda line: [] if line.startswith("> ") else [line]),
    "trailing-spaces": lambda raw: _each_line(raw, lambda line: [line + " \t\xa0" if line else line]),
    "blank-lines": lambda raw: _each_line(raw, lambda line: [line, "", "   ", "\t"] if line.startswith("## ") else [line]),
}


def honest_resave(raw: bytes) -> bytes:
    """Every edit of HONEST_EDITS at once, saved with a BOM and CRLF line endings."""
    for name in ("note-edited", "note-added", "blank-lines", "trailing-spaces", "bom", "crlf"):
        raw = HONEST_EDITS[name](raw)
    return raw


def record_stage1_go(world: World, tools: str) -> None:
    """Record and commit the Stage 1 go of ``world``: with summarize --record (the running tools), or as the
    other, Git-bound tools committed at HEAD then would have written it (synthetic older tool bytes)."""
    if tools == "same":
        code, _out, err = run_main(world, "summarize", *pilot_args(world), "--stage", "1", "--record")
        assert code == 0, err
        commit_files(world.root, {}, "synthetic: the recorded summary")
        return
    real = json.loads(er.canonical_json(summarize(world)))
    assert real["decision"]["value"] == "go"
    real["tooling"]["tools/workflow_pilot.py"] = sha(OLD_TOOL)
    commit_files(world.root, {"tools/workflow_pilot.py": OLD_TOOL}, "synthetic: the tools when summarize --record ran")
    commit_files(world.root, summary_files(real), "synthetic: the recorded summary")


def committed_stage1(world: World) -> dict:
    return json.loads((world.root / wp.PILOT_REL / CAMPAIGN / "stage1-summary.json").read_text(encoding="utf-8"))


def test_the_summary_records_a_normalized_hash_beside_each_review_hash(world: World) -> None:
    """inputs.runs[].reviewNormalized is {"version": 1, "sha256": ...} beside every review hash and null where no
    review was read; the Markdown lists it."""
    summary = summarize(world)
    entries = {item["id"]: item for item in summary["inputs"]["runs"]}
    assert sorted(entries) == sorted(stage1_ids())
    for run_id, item in entries.items():
        raw = (world.evidence(run_id) / "review.md").read_bytes()
        assert item["review"] == sha(raw)
        assert item["reviewNormalized"] == {"version": 1, "sha256": er.normalized_review_sha256(raw)}
        assert item["reviewNormalized"]["sha256"] != item["review"]
    run_id = "pilot-demo-a:codex:1"
    assert f"- {run_id}: record {entries[run_id]['record']}, review {entries[run_id]['review']} (normalized v1 " \
           f"{entries[run_id]['reviewNormalized']['sha256']})" in wp.render_markdown(summary)
    (world.evidence(run_id) / "review.md").unlink()
    entry = next(item for item in summarize(world)["inputs"]["runs"] if item["id"] == run_id)
    assert entry["review"] is None and entry["reviewNormalized"] is None


@pytest.mark.parametrize("tools", ["same", "other"])
def test_an_honest_resave_of_every_stage1_review_leaves_the_go_in_force(world: World, tools: str) -> None:
    """After the record, a CRLF, CR or BOM re-save, a '>' note added, edited or removed, trailing spaces and blank
    lines, one by one and all at once on all 8 Stage 1 reviews, keep every normalized hash: Stage 2 proceeds and the
    all-stage summary is not held, whichever tools recorded the summary."""
    record_stage1_go(world, tools)
    campaign = wp.load_campaign(world.root, CAMPAIGN)
    committed = wp._committed_stage1(world.root, campaign)
    paths = [world.evidence(run_id) / "review.md" for run_id in stage1_ids()]
    originals = {path: path.read_bytes() for path in paths}
    for name, edit in list(HONEST_EDITS.items()) + [("all", honest_resave)]:
        for path, raw in originals.items():
            path.write_bytes(edit(raw))
            assert path.read_bytes() != raw, name
        notes: list[str] = []
        assert wp._stage1_matches(world.root, campaign, str(world.pilot), committed, notes) is None, name
        assert bool(notes) == (tools == "other"), (name, notes)
        assert summarize(world)["decision"]["value"] == "go", name
    do_run(world, "pilot-demo-a:codex:2", session=LATER)  # its run-prepare passes the gate
    summary = summarize(world, "all")
    assert HELD not in summary["decision"]["reasons"], summary["decision"]
    assert not [run["id"] for run in summary["runs"] if run["status"] == "invalid"]


@pytest.mark.parametrize("tools", ["same", "other"])
@pytest.mark.parametrize("edit", ["skill-verdict", "skill-reason", "skill-reviewer", "skill-severity", "skill-deleted",
                                  "baseline-verdict", "baseline-reviewer", "baseline-false-accusation-added",
                                  "baseline-false-accusation-removed", "baseline-deleted"])
def test_a_changed_stage1_review_holds_stage_2_whichever_tools_recorded_it(world: World, tools: str, edit: str) -> None:
    """After the Stage 1 go is recorded, with the running tools or with other (Git-bound) tools, a changed verdict,
    reason, reviewer or severity, a false accusation added or removed, or a deleted review, of a skill run or a
    baseline, is named with its run and file, holds Stage 2 and leaves the all-stage summary incomplete without
    making Stage 2 runs invalid, even where the decision stays go. Restoring the content clears it, also when the
    restored file is saved with CRLF and a note (REG-1, NEW-3 and HONEST-F2, now by normalized hash)."""
    skill, base = "pilot-demo-a:codex:1", "pilot-demo-a:codex:baseline:1"
    accused = ACCUSATIONS + "response:1-2: high\n"
    if edit == "skill-reason":  # 23 of 24 claims supported still meets the 95% target
        _set_review(world, skill, "edge:e1: supported", f"edge:e1: qualified {EM} a synthetic reason")
    elif edit == "baseline-false-accusation-removed":
        _set_review(world, base, ACCUSATIONS, accused)
    record_stage1_go(world, tools)
    do_run(world, "pilot-demo-a:codex:2", session=LATER)
    originals = {run_id: (world.evidence(run_id) / "review.md").read_bytes() for run_id in (skill, base)}
    changed = base if edit.startswith("baseline") else skill
    review = world.evidence(changed) / "review.md"
    if edit.endswith("-deleted"):
        review.unlink()
    else:
        old, new = {"skill-verdict": ("demo-a-f01: covered node:load", "demo-a-f01: missing"),
                    "skill-reason": ("a synthetic reason", "another synthetic reason"),
                    "skill-reviewer": (f"Reviewer: {REVIEWER}", "Reviewer: Another Reviewer (synthetic)"),
                    "skill-severity": ("\nf1: agree\n", "\nf1: too-high\n"),
                    "baseline-verdict": ("demo-a-f01: covered response:1-2", "demo-a-f01: missing"),
                    "baseline-reviewer": (f"Reviewer: {REVIEWER}", "Reviewer: Another Reviewer (synthetic)"),
                    "baseline-false-accusation-added": (ACCUSATIONS, accused),
                    "baseline-false-accusation-removed": (accused, ACCUSATIONS)}[edit]
        _set_review(world, changed, old, new)
        assert not wp.check_file(review, root=world.root)
    code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:claude-code:2", *pilot_args(world))
    where = f"{changed} (evidence/{er.run_dir_name(changed)}/review.md)"
    assert code == 1 and f"1 Stage 1 review(s) changed since the summary was recorded: {where} " in err, err
    if edit.endswith("-deleted"):
        assert f"{where} was deleted." in err, err
    else:
        recorded = next(item for item in committed_stage1(world)["inputs"]["runs"] if item["id"] == changed)
        now = er.normalized_review_sha256(review.read_bytes())
        assert f"{where} changed (normalized sha256 {now[:12]}..., recorded " \
               f"{recorded['reviewNormalized']['sha256'][:12]}...)." in err, err
    assert f"Stage 1 reviews are final once the Stage 1 summary is recorded (review normalization v1): {RESTORE}" in err
    summary = summarize(world, "all")
    assert summary["decision"]["value"] == "incomplete" and HELD in summary["decision"]["reasons"], summary["decision"]
    assert not [run["id"] for run in summary["runs"] if run["status"] == "invalid"]
    assert any(f"review(s) changed since the summary was recorded: {where}" in note
               for note in summary["verification"]["notes"]), summary["verification"]["notes"]
    for run_id, raw in originals.items():
        (world.evidence(run_id) / "review.md").write_bytes(honest_resave(raw))
    code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:claude-code:2", *pilot_args(world))
    assert code == 0, err


@pytest.mark.parametrize("counted", ["later-count", "read-later"])
def test_rc2_1_a_later_count_of_one_baseline_and_a_resave_of_another_leave_an_other_tools_go_in_force(
        world: World, monkeypatch: pytest.MonkeyPatch, counted: str) -> None:
    """RC2-1, closed: with other (Git-bound) tools, a later tool version that counts one baseline's false accusations
    differently (a changed count, or a baseline the recording tools judged invalid and did not read, whose accusation
    the running tools now count), together with a CRLF re-save and a note of another baseline's review, changes the
    baselines' false accusations total but neither holds Stage 2 nor the all-stage summary: tool-counted fields are
    not compared across tool versions, and the re-saved review keeps its normalized hash."""
    first, resaved = "pilot-demo-a:codex:baseline:1", "pilot-demo-b:claude-code:baseline:1"
    if counted == "later-count":
        record_stage1_go(world, "other")
        earlier_metrics = wp._run_metrics

        def later_metrics(state, campaign):
            metrics = earlier_metrics(state, campaign)
            if state.run["id"] == first:
                metrics["accusations"] = dict(metrics["accusations"], low=metrics["accusations"]["low"] + 1)
            return metrics
        monkeypatch.setattr(wp, "_run_metrics", later_metrics)
    else:
        _set_review(world, first, ACCUSATIONS, ACCUSATIONS + "response:1-2: low\n")
        earlier_protocol = wp._protocol

        def recording_protocol(state, campaign, stage1, stage1_problem=None):
            earlier_protocol(state, campaign, stage1, stage1_problem)
            if state.run["id"] == first:
                state.invalid.append("a synthetic rule of the recording tools that a later fix drops")
        with pytest.MonkeyPatch.context() as recording:
            recording.setattr(wp, "_protocol", recording_protocol)
            record_stage1_go(world, "other")
        assert next(item for item in committed_stage1(world)["inputs"]["runs"] if item["id"] == first)["review"] is None
    path = world.evidence(resaved) / "review.md"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n") + b"> a note added after the record (synthetic)\r\n")
    later = summarize(world)
    assert later["decision"]["value"] == "go"
    assert later["baselines"]["falseAccusations"] != committed_stage1(world)["baselines"]["falseAccusations"]
    do_run(world, "pilot-demo-a:codex:2", session=LATER)  # its run-prepare passes the gate
    code, out, err = run_main(world, "run-prepare", "pilot-demo-a:claude-code:2", *pilot_args(world))
    assert code == 0 and "recorded with other tools" in out, err
    summary = summarize(world, "all")
    assert HELD not in summary["decision"]["reasons"], summary["decision"]
    assert not [run["id"] for run in summary["runs"] if run["status"] == "invalid"]


@pytest.mark.parametrize("later", ["count", "protocol-and-resave"])
def test_a_later_tool_judgement_of_an_unchanged_review_leaves_an_other_tools_go_in_force(
        world: World, monkeypatch: pytest.MonkeyPatch, later: str) -> None:
    """With other (Git-bound) tools, a later tool version that counts an unchanged baseline review differently, or
    that judges a baseline invalid (so its review is not read) after a CRLF re-save, neither holds Stage 2 nor names
    the run: only normalized review hashes are compared (REG-1, INTEGRITY-F1, HONEST-F2)."""
    record_stage1_go(world, "other")
    base = "pilot-demo-a:codex:baseline:1"
    if later == "count":
        earlier_metrics = wp._run_metrics

        def later_metrics(state, campaign):
            metrics = earlier_metrics(state, campaign)
            if state.run["id"] == base:
                metrics["ess"] = max(0, metrics["ess"] - 1)
            return metrics
        monkeypatch.setattr(wp, "_run_metrics", later_metrics)
    else:
        earlier_protocol = wp._protocol

        def later_protocol(state, campaign, stage1, stage1_problem=None):
            earlier_protocol(state, campaign, stage1, stage1_problem)
            if state.run["id"] == base:
                state.invalid.append("a later synthetic protocol rule")
        monkeypatch.setattr(wp, "_protocol", later_protocol)
        review = world.evidence(base) / "review.md"
        review.write_bytes(review.read_bytes().replace(b"\n", b"\r\n"))
    summary = summarize(world)
    assert summary["decision"]["value"] == "go"
    side = next(row for row in summary["baselines"]["paired"] if (row["task"], row["host"]) == ("pilot-demo-a", "codex"))
    assert side["baseline"]["ess"] == (side["baseline"]["ESS"] - 1 if later == "count" else 0)
    code, out, err = run_main(world, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(world))
    assert code == 0 and "recorded with other tools" in out, err


@pytest.mark.parametrize("review", ["untouched", "resaved"])
def test_a_baseline_review_the_recording_tools_did_not_read_is_not_compared(
        world: World, monkeypatch: pytest.MonkeyPatch, review: str) -> None:
    """With other (Git-bound) tools that judged a reviewed baseline invalid, the summary lists no review of it (no
    hash, no normalized hash); running tools that judge it valid and read its review.md (untouched, or re-saved with
    CRLF) neither hold Stage 2 nor say the review changed: only the tools' judgement changed (NEW-1, INTEGRITY-F1)."""
    base = "pilot-demo-a:codex:baseline:1"
    earlier_protocol = wp._protocol

    def recording_protocol(state, campaign, stage1, stage1_problem=None):
        earlier_protocol(state, campaign, stage1, stage1_problem)
        if state.run["id"] == base:
            state.invalid.append("a synthetic rule of the recording tools that a later fix drops")
    with pytest.MonkeyPatch.context() as recording:
        recording.setattr(wp, "_protocol", recording_protocol)
        record_stage1_go(world, "other")
    entry = next(item for item in committed_stage1(world)["inputs"]["runs"] if item["id"] == base)
    assert entry["review"] is None and entry["reviewNormalized"] is None
    path = world.evidence(base) / "review.md"
    if review == "resaved":
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    side = next(row for row in summarize(world)["baselines"]["paired"]
                if (row["task"], row["host"]) == ("pilot-demo-a", "codex"))
    assert side["baseline"]["reviewed"] is True
    code, out, err = run_main(world, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(world))
    assert code == 0 and "recorded with other tools" in out, err
    reasons = summarize(world, "all")["decision"]["reasons"]
    assert not [reason for reason in reasons if "not re-verified" in reason], reasons


@pytest.mark.parametrize("later", ["rule", "count"])
def test_a_resave_after_a_later_tool_change_leaves_an_other_tools_go_in_force(
        world: World, monkeypatch: pytest.MonkeyPatch, later: str) -> None:
    """With other (Git-bound) tools, a later tool version that finds a problem in a baseline review, or counts a skill
    run's claims differently, leaves the go in force, before and after a CRLF re-save of that review (NEW-2's hold is
    gone); a changed verdict in it is still held, and restoring the content clears it."""
    record_stage1_go(world, "other")
    run_id = "pilot-demo-a:codex:baseline:1" if later == "rule" else "pilot-demo-a:codex:1"
    if later == "rule":
        earlier_check = wp.check_review

        def later_check(record, display, ctx):
            problems, data = earlier_check(record, display, ctx)
            if ctx.run_id == run_id:
                problems = problems + [er.Problem(display, 1, er.ERROR, "Task", "a later synthetic review rule")]
            return problems, data
        monkeypatch.setattr(wp, "check_review", later_check)
    else:
        earlier_metrics = wp._run_metrics

        def later_metrics(state, campaign):
            metrics = earlier_metrics(state, campaign)
            if state.run["id"] == run_id:
                observed = dict(metrics["claims"]["observed"])
                observed["supported"], observed["qualified"] = observed["supported"] - 1, observed["qualified"] + 1
                metrics["claims"] = dict(metrics["claims"], observed=observed)
            return metrics
        monkeypatch.setattr(wp, "_run_metrics", later_metrics)
    path = world.evidence(run_id) / "review.md"
    original = path.read_bytes()
    code, out, err = run_main(world, "run-prepare", "pilot-demo-a:claude-code:2", *pilot_args(world))
    assert code == 0 and "recorded with other tools" in out, err
    path.write_bytes(original.replace(b"\n", b"\r\n"))
    code, out, err = run_main(world, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(world))
    assert code == 0 and "recorded with other tools" in out, err
    path.write_bytes(original.replace(b"demo-a-f02: covered", b"demo-a-f02: partial"))
    code, _out, err = run_main(world, "run-prepare", "pilot-demo-b:codex:2", *pilot_args(world))
    assert code == 1 and f"{run_id} (evidence/{er.run_dir_name(run_id)}/review.md) changed" in err, err
    path.write_bytes(honest_resave(original))
    code, out, err = run_main(world, "run-prepare", "pilot-demo-b:codex:2", *pilot_args(world))
    assert code == 0 and "recorded with other tools" in out, err


def _without_normalized_hashes(world: World, tools: str) -> dict:
    """Commit the Stage 1 go of ``world`` as tools older than review normalization v1 would have recorded it (no
    inputs.runs[].reviewNormalized), naming the running tools or other (Git-bound) tools; returns the real summary."""
    real = json.loads(er.canonical_json(summarize(world)))
    assert real["decision"]["value"] == "go"
    older = json.loads(er.canonical_json(real))
    for item in older["inputs"]["runs"]:
        del item["reviewNormalized"]
    if tools == "other":
        older["tooling"]["tools/workflow_pilot.py"] = sha(OLD_TOOL)
        commit_files(world.root, {"tools/workflow_pilot.py": OLD_TOOL}, "synthetic: the tools when recorded")
    commit_files(world.root, summary_files(older), "synthetic: a summary recorded by older tools")
    return real


@pytest.mark.parametrize("tools", ["same", "other"])
def test_a_stage1_summary_without_normalized_review_hashes_is_refused(world: World, tools: str) -> None:
    """A Stage 1 summary recorded before normalized review hashes existed is refused, whichever tools it names, as a
    hold (not a missing go, STATS-1), with the advice to record Stage 1 again only while no Stage 2 run has been
    prepared and the commit is unpushed; there is no fallback to re-derived verdicts. Another normalization version is
    held too; a malformed entry is refused as a summary that summarize --record never writes."""
    real = _without_normalized_hashes(world, tools)
    code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(world))
    assert code == 1 and wp.NO_REVIEW_HASHES in err, err
    assert "Only while no Stage 2 run has been prepared and the summary commit is not pushed, record Stage 1 again " \
           "with the current tools" in wp.NO_REVIEW_HASHES
    assert "a summary recorded again after Stage 2 runs were prepared makes each of them invalid" in wp.NO_REVIEW_HASHES
    assert not world.evidence("pilot-demo-a:codex:2").exists()
    campaign = wp.load_campaign(world.root, CAMPAIGN)
    planned = {item["id"]: item for item in campaign.plan()}
    older = wp._committed_stage1(world.root, campaign)
    assert wp._stage1_go(older, campaign) is None and wp._stage1_go(real, campaign) is None
    held = wp._stage1_matches(world.root, campaign, str(world.pilot), older)
    assert isinstance(held, wp.Stage1Unverified) and held == wp.NO_REVIEW_HASHES
    assert held.remedy == wp.NO_REVIEW_HASHES_REMEDY
    assert sorted(wp._recorded_reviews(real, planned)) == sorted(stage1_ids())
    run_id = "pilot-demo-a:codex:1"
    for change, expected, hold in (
            ({"version": 2}, f"records the review of {run_id} with review normalization v2; these tools implement v1 only",
             True),
            ({"version": True}, f"has a malformed normalized review hash for {run_id}", False),
            ({"sha256": "A" * 64}, f"has a malformed normalized review hash for {run_id}", False),
            ({"extra": 1}, f"has a malformed normalized review hash for {run_id}", False),
            (None, f"has a malformed normalized review hash for {run_id}", False)):
        forged = json.loads(er.canonical_json(real))
        entry = next(item for item in forged["inputs"]["runs"] if item["id"] == run_id)
        entry["reviewNormalized"] = None if change is None else dict(entry["reviewNormalized"], **change)
        reason = wp._recorded_reviews(forged, planned)
        assert isinstance(reason, str) and expected in reason, change
        assert isinstance(reason, wp.Stage1Unverified) == hold, change


def test_stage2_runs_under_a_summary_without_normalized_review_hashes_stay_valid(world: World) -> None:
    """STATS-1: Stage 2 runs prepared (by the 0.3.0 gate, simulated) under a Stage 1 go that it recorded without
    normalized review hashes are not made invalid by these tools: the all-stage summary is incomplete, with a note
    that gives the advice, and cannot be recorded (before, it was a recordable targets-missed with every Stage 2 run
    invalid)."""
    _without_normalized_hashes(world, "other")
    with pytest.MonkeyPatch.context() as earlier:
        earlier.setattr(wp, "_recorded_reviews", lambda summary, planned: {})  # the 0.3.0 gate never read them
        for run_id in [f"{task}:{host}:{rep}" for task, _repo, _entry in TASKS for host in HOSTS for rep in (2, 3)]:
            do_run(world, run_id, session=LATER)
    summary = summarize(world, "all")
    assert summary["decision"]["value"] == "incomplete" and HELD in summary["decision"]["reasons"], summary["decision"]
    assert not [run["id"] for run in summary["runs"] if run["status"] == "invalid"]
    assert any(wp.NO_REVIEW_HASHES in note and note.endswith(f"; {wp.NO_REVIEW_HASHES_REMEDY} and summarize again")
               for note in summary["verification"]["notes"]), summary["verification"]["notes"]
    code, _out, err = run_main(world, "summarize", *pilot_args(world), "--stage", "all", "--record")
    assert code == 1 and "the decision is incomplete" in err, err


def test_a_same_tools_summary_that_nulls_a_read_review_does_not_unlock_stage_2(world: World) -> None:
    """INTEGRITY-1: with the same tools, the re-computation shows which reviews the tools read, and the normalized
    review hashes are part of the comparison, so a summary that lists a read review with null hashes (which would
    exempt it from the finality rule) does not unlock Stage 2."""
    real = json.loads(er.canonical_json(summarize(world)))
    run_id = "pilot-demo-a:codex:1"
    entry = next(item for item in real["inputs"]["runs"] if item["id"] == run_id)
    entry["review"] = entry["reviewNormalized"] = None
    commit_files(world.root, summary_files(real), "synthetic: a summary that nulls a read review")
    code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:codex:2", *pilot_args(world))
    assert code == 1 and "the committed Stage 1 summary differs from a re-computation from the sealed evidence in " \
                         "inputs (a recorded summary is written only by summarize --record)" in err, err


@pytest.mark.parametrize("tools", ["same", "other"])
def test_a_review_restored_into_a_stage1_run_that_did_not_complete_is_named(world: World, tools: str) -> None:
    """STATS-2, HONEST-2: a review.md that reappears after the record in a Stage 1 baseline that failed (the summary
    lists it without a review) is named with its run and file and the remedy, holds Stage 2 and leaves the all-stage
    summary incomplete without making Stage 2 runs invalid, whichever tools recorded the summary; removing it clears
    it."""
    base = "pilot-demo-a:codex:baseline:1"
    kept = (world.evidence(base) / "review.md").read_bytes()
    redo(world, base, session={"Status": "failed", "Failure": f"host-error {EM} crashed mid-answer (synthetic)",
                               "Prompt sent": "yes"})
    record_stage1_go(world, tools)
    entry = next(item for item in committed_stage1(world)["inputs"]["runs"] if item["id"] == base)
    assert entry["review"] is None and entry["reviewNormalized"] is None
    do_run(world, "pilot-demo-a:codex:2", session=LATER)
    path = world.evidence(base) / "review.md"
    path.write_bytes(kept)
    code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:claude-code:2", *pilot_args(world))
    where = f"{base} (evidence/{er.run_dir_name(base)}/review.md; the run is failed)"
    assert code == 1 and f"1 Stage 1 run(s) that did not complete have a review.md that the summary does not list: " \
                         f"{where}. Remove each named review.md" in err, err
    assert "a recorded summary is written only by summarize --record" not in err, err
    summary = summarize(world, "all")
    assert summary["decision"]["value"] == "incomplete" and HELD in summary["decision"]["reasons"], summary["decision"]
    assert not [run["id"] for run in summary["runs"] if run["status"] == "invalid"]
    assert any(where in note and note.endswith("; remove each named review.md and summarize again")
               for note in summary["verification"]["notes"]), summary["verification"]["notes"]
    assert not any("restore the Stage 1 evidence" in note for note in summary["verification"]["notes"])
    path.unlink()
    code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:claude-code:2", *pilot_args(world))
    assert code == 0, err


def test_a_later_tool_rule_that_rejects_a_recorded_skill_review_is_named_with_its_remedy(
        world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """HONEST-1: with other (Git-bound) tools, a later review rule that rejects an unchanged Stage 1 skill review
    holds Stage 2 with its own message: it names the review, says it is final and must not be edited, and that Stage 2
    needs the rule reverted; the all-stage summary is incomplete with that remedy (not "fetch or verify the corpus")
    and no Stage 2 run becomes invalid. Editing the review as the rule asks changes its hash; restoring it and
    reverting the rule clears the hold."""
    record_stage1_go(world, "other")
    do_run(world, "pilot-demo-a:codex:2", session=LATER)
    skill = "pilot-demo-a:codex:1"
    path = world.evidence(skill) / "review.md"
    original = path.read_bytes()
    earlier_check = wp.check_review

    def later_check(record, display, ctx):
        problems, data = earlier_check(record, display, ctx)
        if ctx.run_id == skill:
            problems = problems + [er.Problem(display, 1, er.ERROR, "Claims", "a later synthetic review rule")]
        return problems, data
    rejected = (f"these tools reject 1 Stage 1 review(s) that are unchanged since the summary was recorded (their "
                f"normalized hashes match): {skill}; a re-computation of Stage 1 with these tools gives incomplete (")
    with pytest.MonkeyPatch.context() as later:
        later.setattr(wp, "check_review", later_check)
        assert summarize(world)["decision"]["value"] == "incomplete"
        code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:claude-code:2", *pilot_args(world))
        assert code == 1 and rejected in err, err
        assert "Those reviews are final: do not edit them" in err and "Stage 2 needs the tool change that rejects " \
               "them reverted (the tools that recorded the Stage 1 summary accept them)" in err, err
        summary = summarize(world, "all")
        assert summary["decision"]["value"] == "incomplete" and HELD in summary["decision"]["reasons"]
        assert not [run["id"] for run in summary["runs"] if run["status"] == "invalid"]
        notes = summary["verification"]["notes"]
        assert any(rejected in note and note.endswith("; do not edit those Stage 1 reviews; revert the tool change "
                                                      "that rejects them and summarize again") for note in notes), notes
        assert not any("fetch or verify the corpus" in note for note in notes), notes
        _set_review(world, skill, "Date: 2026-10-21", "Date: 2026-10-22")  # what the rule asks would change it too
        code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:claude-code:2", *pilot_args(world))
        assert code == 1 and f"1 Stage 1 review(s) changed since the summary was recorded: {skill} " in err, err
        path.write_bytes(honest_resave(original))
        code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:claude-code:2", *pilot_args(world))
        assert code == 1 and rejected in err, err
    code, out, err = run_main(world, "run-prepare", "pilot-demo-a:claude-code:2", *pilot_args(world))
    assert code == 0 and "recorded with other tools" in out, err


@pytest.mark.parametrize("tools", ["same", "other"])
def test_a_later_count_that_turns_the_recorded_go_into_stop(world: World, tools: str) -> None:
    """CHECK (predates the normalized hashes): with other (Git-bound) tools, a later count change that makes the
    unchanged Stage 1 evidence a stop holds Stage 2 with the revert remedy, and the all-stage summary is incomplete
    without making Stage 2 runs invalid; with the same tools the committed go was never theirs, so it stays a plain
    reason."""
    record_stage1_go(world, tools)
    do_run(world, "pilot-demo-a:codex:2", session=LATER)
    earlier_targets = wp.compute_targets

    def later_targets(runs, *args, **kwargs):
        targets = earlier_targets(runs, *args, **kwargs)
        if runs and all(run.get("stage", 1) == 1 for run in runs):
            for target in targets:
                if target["key"] == "essentialFactRecall":
                    target["met"] = False
        return targets
    unverified = "a re-computation of Stage 1 with these tools gives stop, not go; the sealed Stage 1 inputs and the " \
                 "reviews the summary lists are unchanged"
    with pytest.MonkeyPatch.context() as later:
        later.setattr(wp, "compute_targets", later_targets)
        assert summarize(world)["decision"]["value"] == "stop"
        code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:claude-code:2", *pilot_args(world))
        summary = summarize(world, "all")
        invalid = [run["id"] for run in summary["runs"] if run["status"] == "invalid"]
        if tools == "other":
            assert code == 1 and unverified in err and "Stage 2 needs that tool change reverted" in err, err
            assert summary["decision"]["value"] == "incomplete" and HELD in summary["decision"]["reasons"]
            assert not invalid, invalid
            assert any(unverified in note and note.endswith("; revert the tool change that counts the unchanged "
                                                            "Stage 1 evidence differently and summarize again")
                       for note in summary["verification"]["notes"]), summary["verification"]["notes"]
        else:
            assert code == 1 and "a re-computation of Stage 1 from the sealed evidence gives stop, not go" in err, err
            assert unverified not in err and invalid, invalid
    code, _out, err = run_main(world, "run-prepare", "pilot-demo-a:claude-code:2", *pilot_args(world))
    assert code == 0, err


def test_a_retriable_failure_stays_open_in_the_early_stop_indicators(retry_world: World) -> None:
    """A Stage 1 failure the policy lets the operator retry is named with its retry command, is open in the
    early-stop bounds, and blocks --record of the computed stop until it is retried (INTEGRITY-F3, STATS-F1)."""
    run_id = "pilot-demo-a:codex:1"
    redo(retry_world, run_id, publish_artifact=False, session=UNSENT, transcript=UNSENT_TRANSCRIPT)
    forget(retry_world, "pilot-demo-b:codex:1")
    assert run_main(retry_world, "run-prepare", "pilot-demo-b:codex:1", *pilot_args(retry_world))[0] == 0
    summary = summarize(retry_world)
    assert summary["decision"]["value"] == "incomplete"
    indicators = summary["decision"]["earlyStopIndicators"]
    assert f"T1: {run_id} failed (host-error); may still be retried" in indicators, indicators
    assert not [item for item in indicators if item.startswith(("T4", "T5"))], indicators
    command = f'python tools/workflow_eval.py run-prepare {run_id} --campaign {CAMPAIGN} --retry "<reason>"'
    assert summary["openRetries"] == [{"id": run_id, "attempt": 1, "command": command}]
    shutil.rmtree(retry_world.workspace("pilot-demo-b:codex:1"))  # fixture setup only
    forget(retry_world, "pilot-demo-b:codex:1")
    do_run(retry_world, "pilot-demo-b:codex:1")
    stop = summarize(retry_world)
    assert stop["decision"]["value"] == "stop" and stop["openRetries"] == summary["openRetries"]
    code, out, err = run_main(retry_world, "summarize", *pilot_args(retry_world), "--stage", "1", "--record")
    assert code == 1 and f"- {run_id} attempt 1: {command}" in out and "retry it before recording" in err, err
    assert not (retry_world.root / wp.PILOT_REL / CAMPAIGN / "stage1-summary.json").exists()
    assert run_main(retry_world, "run-prepare", run_id, *pilot_args(retry_world), "--retry", "crash (synthetic)")[0] == 0
    finish_retry(retry_world, run_id)
    assert summarize(retry_world)["openRetries"] == []


def test_a_run_amended_away_from_completed_names_its_review(world: World) -> None:
    """After an amendment to timed-out or failed, the run's review.md is named with "remove review.md" by the
    amendment, the summary, check and the --record refusal (STATS-F3)."""
    skill = "pilot-demo-a:codex:1"
    evidence = world.evidence(skill)
    (evidence / "session.md").write_text(session_text(skill, **{
        "Status": "timed-out", "Failure": "repair-budget -- ran out of time (synthetic)", "Active minutes": "25",
        "Prompt sent": "yes"}), encoding="utf-8")
    code, out, err = run_main(world, "run-finish", skill, *pilot_args(world), "--amend", "it timed out (synthetic)")
    assert code == 0 and "Next: remove review.md (a timed-out run is not reviewed" in out, out + err
    summary = summarize(world)
    assert summary["decision"]["value"] == "incomplete"
    assert f"1 review problem(s) unresolved: {skill}: a timed-out run is not reviewed; remove review.md" in \
        summary["decision"]["reasons"], summary["decision"]["reasons"]
    messages = [problem.message for problem in wp.check_file(evidence / "review.md", root=world.root)]
    assert messages == ["a timed-out run is not reviewed (its record.json says Status: timed-out); remove review.md."]
    (evidence / "review.md").unlink()
    assert summarize(world)["decision"]["value"] == "stop"
    base = "pilot-demo-b:claude-code:baseline:1"
    base_evidence = world.evidence(base)
    (base_evidence / "session.md").write_text(session_text(base, **{
        "Status": "failed", "Failure": "host-error -- crashed after the answer (synthetic)", "Prompt sent": "yes"}),
        encoding="utf-8")
    assert run_main(world, "run-finish", base, *pilot_args(world), "--amend", "it failed (synthetic)")[0] == 0
    code, _out, err = run_main(world, "summarize", *pilot_args(world), "--stage", "1", "--record")
    assert code == 1 and f"(review problems: {base}); remove review.md of {base} (a run that did not complete is not " \
                         "reviewed) before recording" in err, err


def test_summarize_record_works_with_a_cp1252_stdout(world: World, tmp_path: Path) -> None:
    """summarize --record through a real process whose stdout is a Windows code page (a redirect, a pipe or Git
    Bash without UTF-8 mode) records the summary and prints it (HONEST-F4, DISTCI-F3)."""
    driver = tmp_path / "driver.py"
    driver.write_text(
        "import sys\nfrom pathlib import Path\n"
        f"sys.path.insert(0, {str(TOOLS)!r})\n"
        "import workflow_pilot as wp\n"
        "wp.fetch_workflow_repos.verify_repo = lambda repo, corpus_root: {'name': repo['name'], 'ok': True}\n"
        "wp.workflow_candidate.check = lambda record, root, vsix=None: []\n"
        f"wp._now = lambda: {NOW!r}\n"
        "root = Path(sys.argv.pop(1))\n"
        "sys.exit(wp.main(sys.argv[1:], root=root))\n", encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if not key.startswith(("PYTHONUTF8", "PYTHONIOENCODING"))}
    env.update({"PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0", "PYTHONDONTWRITEBYTECODE": "1",
                "MLVIEW_PUBLIC_CORPUS_DIR": str(world.corpus)})
    result = subprocess.run([sys.executable, str(driver), str(world.root), "summarize", *pilot_args(world), "--stage",
                             "1", "--record"], capture_output=True, env=env, check=False)
    assert result.returncode == 0, result.stderr.decode("cp1252", "replace")
    out = result.stdout.decode("cp1252")
    assert "| Supported claims (observed+inferred; qualified = not-supported) | 24/24 | >=95% | yes |" in out
    assert "Recorded stage1-summary.json and stage1-summary.md" in result.stderr.decode("cp1252")
    recorded = world.root / wp.PILOT_REL / CAMPAIGN / "stage1-summary.md"
    assert recorded.read_bytes().decode("utf-8") == out.replace("\r\n", "\n")
