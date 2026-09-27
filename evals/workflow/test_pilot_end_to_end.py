"""End-to-end test of the Campaign 2 pilot tooling on one synthetic world (SPEC section 8.5, step 1).

One synthetic held-out task, three hosts and a temporary Git corpus checkout with a real sparse
checkout. The test drives the merged tools exactly as the owner and the operator would:

    template -> synthetic decisions (primary and second reviewer) -> check -> freeze -> commit ->
    clone -> candidate capture (stub packager) -> plan -> run-prepare -> the real helper
    publishes -> run-finish -> review-template -> synthetic review -> summarize (go) -> record

and then applies mutations that give stop, incomplete and invalid decisions and integrity errors.
Nothing is monkeypatched between the streams: fetch_workflow_repos.verify_repo, the v2
workflow_candidate.check, check-frozen and the frozen file formats written by the freeze are the
real ones. Only `npm run package` is replaced by a stub that zips the synthetic payload, and the
clock is fixed so the synthetic timeline is ordered.

Every decision, reviewer name, verdict, run-policy value and session fact below is synthetic test
data (reviewers "Test Reviewer (synthetic)" and "Second Test Reviewer (synthetic)"); no real task is
decided and nothing is written into the repository. This is a tooling check: it is not semantic
accuracy, human review, a pilot run, a native session or live-host validation.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import eval_records as er  # noqa: E402
import fetch_workflow_repos  # noqa: E402
import package_skill  # noqa: E402
import workflow_candidate as wc  # noqa: E402
import workflow_decisions as wd  # noqa: E402
import workflow_pilot as wp  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

EM = "—"
CAMPAIGN = "pilot-e2e"
TASK = "pilot-demo"
HOSTS = ["codex", "copilot", "claude-code"]
REVIEWER = "Test Reviewer (synthetic)"
SECOND = "Second Test Reviewer (synthetic)"
DATE = "2026-10-01"
FROZEN_AT = "2026-10-01T12:00:00Z"
CAPTURED_AT = "2026-10-02T09:00:00Z"
RUN_CLOCK = "2026-10-10T10:00:00Z"
SUMMARY_CLOCK = "2026-10-20T08:00:00Z"
STARTED = "2026-10-10T09:00:00Z"
ENDED = "2026-10-10T09:15:00Z"
MODEL = "synthetic-model (synthetic)"
REASONING = "default (synthetic)"
INVOCATION = "skill picker (synthetic)"
TARGETS = {"structurallyValid": 1.0, "exactAnchors": 1.0, "supportedClaimPrecision": 0.95,
           "essentialFactRecall": 0.85, "knownUnresolvedQualified": 1.0, "highSeverityFalseAccusations": 0}
MACHINE_MARKERS = ("/Users/", "/home/", "/private/", "C:\\", "C:/")

DEMO_FILES = {
    "train.py": ("import lib.model as model\n"
                 "steps = 40\n"
                 "for step in range(steps):\n"
                 "    model.update(step)\n"
                 "model.save('out.bin')\n"),
    "lib/model.py": ("def update(step):\n"
                     "    return step\n"
                     "\n"
                     "\n"
                     "def save(path):\n"
                     "    return path\n"),
    "README.md": "Synthetic README outside the sparse set; never materialised or copied.\n",
    "docs/notes.txt": "Synthetic notes outside the sparse set.\n",
}
SPARSE = ["/train.py", "lib"]


# --------------------------------------------------------------------------------------------
# Small helpers


def git_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_AUTHOR_NAME": "Synthetic Test", "GIT_AUTHOR_EMAIL": "synthetic@example.invalid",
                "GIT_COMMITTER_NAME": "Synthetic Test", "GIT_COMMITTER_EMAIL": "synthetic@example.invalid"})
    return env


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, env=git_env(), check=False)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout.decode("utf-8").strip()


def commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write_lf(path: Path, text: str) -> None:
    """Write UTF-8 text with LF line endings on every OS (the repository keeps exact bytes)."""
    path.write_bytes(text.encode("utf-8"))


def canonical(value: object) -> bytes:
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def quote(rel: str, line: int, end: int) -> str:
    return er.excerpt(er.source_lines(DEMO_FILES[rel].encode("utf-8"), None), line, end)


def anchor(ident: str, rel: str, line: int, end: int) -> dict:
    return {"id": ident, "file": rel, "line": line, "endLine": end, "quote": quote(rel, line, end)}


def decisions(root: Path, corpus: Path, *argv: str) -> tuple[int, str]:
    buffer = io.StringIO()
    code = wd.main(list(argv), root=root, corpus=corpus, out=buffer)
    return code, buffer.getvalue()


def pilot(root: Path, *argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = wp.main(list(argv), root=root)
    return code, out.getvalue(), err.getvalue()


def replace_line(text: str, heading: str | None, old: str, new: list[str]) -> str:
    """Replace the first line ``old`` after ``## heading`` (or anywhere when heading is None)."""
    lines = text.split("\n")
    start = 0 if heading is None else lines.index(f"## {heading}") + 1
    for index in range(start, len(lines)):
        if heading is not None and lines[index].startswith("## "):
            break
        if lines[index] == old:
            lines[index:index + 1] = new
            return "\n".join(lines)
    raise AssertionError(f"{old!r} not found under {heading!r}")


def insert_before(text: str, marker: str, lines: list[str]) -> str:
    assert marker in text
    return text.replace(marker, "\n".join(lines) + "\n" + marker, 1)


def no_machine_paths(data: bytes | str) -> bool:
    text = data.decode("utf-8") if isinstance(data, bytes) else data
    return not any(marker in text for marker in MACHINE_MARKERS)


# --------------------------------------------------------------------------------------------
# The synthetic world


@dataclass
class World:
    base: Path
    corpus: Path
    work: Path       # where the owner files are decided and the freeze is written
    clone: Path      # a fresh clone of the frozen state: capture, runs and summaries
    pilot_dir: Path  # MLVIEW_PILOT_DIR, outside every Git work tree

    def evidence(self, run_id: str) -> Path:
        return self.pilot_dir / "evidence" / er.run_dir_name(run_id)

    def workspace(self, run_id: str) -> Path:
        return self.pilot_dir / "workspaces" / er.run_dir_name(run_id)

    def campaign_dir(self) -> Path:
        return self.clone / wp.PILOT_REL / CAMPAIGN

    def args(self) -> list[str]:
        return ["--campaign", CAMPAIGN, "--pilot-dir", str(self.pilot_dir)]


def make_corpus(corpus: Path) -> str:
    """A pinned Git checkout of the synthetic repository with a real non-cone sparse checkout."""
    repo = corpus / "demo"
    repo.mkdir(parents=True)
    git(repo, "init", "--quiet")
    git(repo, "config", "core.autocrlf", "false")
    for rel, text in DEMO_FILES.items():
        write_bytes(repo / rel, text.encode("utf-8"))
    sha = commit_all(repo, "synthetic corpus")
    git(repo, "sparse-checkout", "set", "--no-cone", *SPARSE)
    assert not (repo / "README.md").exists() and (repo / "train.py").is_file()
    return sha


def make_mlview(root: Path, sha: str) -> None:
    """A synthetic MLView checkout: one held-out task, three hosts, the real portable skill."""
    root.mkdir(parents=True)
    git(root, "init", "--quiet")
    tasks = {"version": 1, "hosts": HOSTS, "repetitions": 3, "pilotTargets": dict(TARGETS), "tasks": [
        {"id": "dev-demo", "split": "development", "title": "Synthetic development task", "repository": "MLView",
         "entrypoints": ["samples/synthetic.py"], "prompt": "Synthetic development prompt.",
         "referenceStatus": "needs-human-review"},
        {"id": TASK, "split": "heldout", "title": "Synthetic demo", "repository": "demo",
         "url": "https://example.invalid/demo", "commit": sha, "entrypoints": ["train.py"],
         "prompt": "Explain the synthetic training loop and its defaults.", "referenceStatus": "needs-human-review"}]}
    ledger = {"taskId": TASK, "repositoryCommit": sha, "status": "draft-needs-human-review",
              "review": {"reviewer": None, "decision": "pending"},
              "scenario": {"description": "Inspect train.py with its synthetic defaults and no overrides.",
                           "entrypoints": ["train.py"], "arguments": []},
              "facts": [
                  {"id": "demo-f01", "claim": "The synthetic loop runs forty update steps by default.",
                   "basis": "observed", "essential": True, "anchors": [anchor("demo-a01", "train.py", 2, 3)],
                   "review": "pending"},
                  {"id": "demo-f02", "claim": "Each synthetic step calls model.update with the step index.",
                   "basis": "observed", "essential": True, "anchors": [anchor("demo-a02", "train.py", 4, 4)],
                   "review": "pending"},
                  {"id": "demo-f03", "claim": "The synthetic update helper returns its step argument unchanged.",
                   "basis": "observed", "essential": False, "anchors": [anchor("demo-a03", "lib/model.py", 1, 2)],
                   "review": "pending"}],
              "unknowns": ["The contents written to the synthetic output file are not established by the source."],
              "nonDefects": ["Saving to a fixed synthetic file name is intentional for this example."]}
    package = {"name": "mlview", "version": "0.3.0",
               "contributes": {"commands": [{"command": "mlview.openGeneratedDiagram"}]}}
    files: dict[str, bytes] = {
        ".gitattributes": b"* -text\n",
        ".gitignore": b"vscode-extension/out/\n*.vsix\n",
        "LICENSE": b"MIT License (synthetic)\n",
        "THIRD_PARTY_NOTICES.md": b"Synthetic notices.\n",
        "contracts/workflow.schema.json": (ROOT / "contracts/workflow.schema.json").read_bytes(),
        wp.TASKS_REL: canonical(tasks),
        wp.REPOSITORIES_REL: canonical({"repos": [
            {"name": "demo", "url": "https://example.invalid/demo", "sha": sha, "license": "synthetic",
             "redistribute": False, "sparse": SPARSE}]}),
        f"{wd.CANDIDATES_REL}/{TASK}.json": canonical(ledger),
        "webview/dist/mlview.js": b"renderViewer(); // synthetic\n",
        "webview/dist/mlview.css": b"body { margin: 0; } /* synthetic */\n",
        "vscode-extension/package.json": canonical(package),
        "vscode-extension/media/mlview.js": b"renderViewer(); // synthetic\n",
        "vscode-extension/media/mlview.css": b"body { margin: 0; } /* synthetic */\n",
    }
    files.update({f"{wp.SKILL_REL}/{rel}": data
                  for rel, data in package_skill.canonical_files(ROOT / wp.SKILL_REL).items()})
    for rel, data in files.items():
        write_bytes(root / rel, data)
    if os.name != "nt":
        (root / wp.HELPER_REL).chmod(0o755)
    commit_all(root, "synthetic MLView checkout")


def stub_package(root: Path, output: Path) -> None:
    """What `npm run package` does, in miniature: compile the ignored bundle, then zip the payload."""
    bundle = root / "vscode-extension/out/extension.js"
    write_bytes(bundle, b"activate(); // synthetic\n")
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("extension/package.json", (root / "vscode-extension/package.json").read_bytes())
        archive.writestr("extension/out/extension.js", bundle.read_bytes())
        for media in sorted((root / "vscode-extension/media").iterdir()):
            archive.writestr(f"extension/media/{media.name}", media.read_bytes())
        archive.writestr("extension/LICENSE.txt", (root / "LICENSE").read_bytes())
        archive.writestr("extension/THIRD_PARTY_NOTICES.md", (root / "THIRD_PARTY_NOTICES.md").read_bytes())


def real_check_frozen(corpus: Path):
    def check(root: Path) -> None:
        code, out = decisions(root, corpus, "check-frozen")
        if code:
            raise wc.CaptureError(f"check-frozen did not pass: {out}")
    return check


def primary_decisions(root: Path) -> str:
    """The synthetic primary reviewer's file, built from the pristine template."""
    text = (root / wd.DECISIONS_REL / f"{TASK}.md").read_text(encoding="utf-8")
    text = text.replace("\nReviewer:\n", f"\nReviewer: {REVIEWER}\n", 1).replace("\nDate:\n", f"\nDate: {DATE}\n", 1)
    text = replace_line(text, "Scenario", "Decision: pending", ["Decision: accept"])
    text = replace_line(text, "Fact demo-f01", "Decision: pending", ["Decision: accept"])
    text = replace_line(text, "Fact demo-f02", "Decision: pending", ["Decision: accept"])
    text = replace_line(text, "Fact demo-f03", "Decision: pending", [
        "Decision: qualify", "Wording: The synthetic update helper returns the step index it receives (synthetic).",
        "Reason: synthetic wording change for the end-to-end test"])
    text = replace_line(text, "Unknown demo-u01", "Decision: pending", ["Decision: accept"])
    text = replace_line(text, "Unknown demo-u01", "Runs must state:", ["Runs must state: yes"])
    text = replace_line(text, "Non-defect demo-n01", "Decision: pending", ["Decision: accept"])
    return insert_before(text, "## Disagreements", [
        "## Added fact demo-h01", "Wording: The synthetic save helper returns the path it is given (synthetic).",
        "Basis: observed", "Essential: yes", "Anchors: lib/model.py:5-6",
        "Reason: synthetic added fact for the end-to-end test", ""])


def second_decisions(root: Path) -> str:
    text = (root / wd.DECISIONS_REL / f"{TASK}.second.md").read_text(encoding="utf-8")
    text = text.replace("\nReviewer:\n", f"\nReviewer: {SECOND}\n", 1).replace("\nDate:\n", f"\nDate: {DATE}\n", 1)
    text = replace_line(text, "Fact demo-f01", "Decision: pending", ["Decision: reject",
                                                                    "Reason: synthetic disagreement"])
    return text.replace("\nReview: pending\n", "\nReview: complete\n")


def policy_decisions(root: Path) -> str:
    text = (root / wd.DECISIONS_REL / "run-policy.md").read_text(encoding="utf-8")
    text = text.replace("\nReviewer:\n", f"\nReviewer: {REVIEWER}\n", 1).replace("\nDate:\n", f"\nDate: {DATE}\n", 1)
    values = {"Model:": f"Model: {MODEL}", "Reasoning:": f"Reasoning: {REASONING}",
              "Invocation:": f"Invocation: {INVOCATION}",
              "Helper Python:": "Helper Python: python3 resolves to a Python 3.12 virtual environment (synthetic)",
              "Active minutes:": "Active minutes: 20", "Repair rounds:": "Repair rounds: 2",
              "Infrastructure retries:": "Infrastructure retries: 0",
              "Qualified claims:": "Qualified claims: not-supported", "Per-host targets:": "Per-host targets: yes",
              "Baseline sessions:": f"Baseline sessions: {len(HOSTS)}",
              "Development adjudication before Stage 1:": "Development adjudication before Stage 1: not-required",
              "Publication:": "Publication: counts, statuses and hashes only (synthetic)",
              "Decision: pending": "Decision: accept", "Review: pending": "Review: complete"}
    return "\n".join(values.get(line, line) for line in text.split("\n"))


def draft(run_id: str) -> dict:
    host = run_id.split(":")[1]
    lines = DEMO_FILES["train.py"].split("\n")
    return {
        "workflowVersion": "1.0", "title": "Synthetic training loop",
        "producer": {"kind": "host-llm", "host": host, "model": "synthetic-model"}, "revision": {"id": "rev-1"},
        "request": {"question": "Explain the synthetic training loop.", "scope": "Selected entrypoint (synthetic).",
                    "entrypoints": ["train.py"], "configuration": "Source defaults; no overrides (synthetic)."},
        "phases": [{"id": "train", "label": "Training"}],
        "nodes": [{"id": "load", "label": "Loop setup", "phase": "train", "basis": "observed", "evidence": ["ev-1"],
                   "detail": "Forty synthetic steps."},
                  {"id": "step", "label": "Update step", "phase": "train", "basis": "inferred", "evidence": ["ev-2"]}],
        "edges": [{"id": "e1", "source": "load", "target": "step", "label": "drives", "basis": "observed",
                   "evidence": ["ev-1"]}],
        "findings": [{"id": "f1", "title": "Synthetic finding", "message": "A synthetic high-severity finding.",
                      "severity": "high", "nodeIds": ["step"], "basis": "observed", "evidence": ["ev-2"]}],
        "evidence": [{"id": "ev-1", "file": "train.py", "line": 2, "endLine": 3, "quote": "\n".join(lines[1:3])},
                     {"id": "ev-2", "file": "train.py", "line": 4, "endLine": 4, "quote": lines[3]}],
        "coverage": {"status": "scoped", "summary": "Synthetic entrypoint inspected.", "inspectedFiles": ["train.py"],
                     "limitations": ["Synthetic limitation: output contents are unknown."]},
    }


def publish(world: World, run_id: str) -> None:
    """The real installed helper publishes the synthetic draft into the prepared workspace."""
    workspace = world.workspace(run_id)
    helper = workspace / wp._skill_destination(run_id.split(":")[1]) / "scripts" / "artifact.py"
    write_lf(workspace / "synthetic.draft.json", json.dumps(draft(run_id)))
    result = subprocess.run([sys.executable, str(helper), "publish", "synthetic.draft.json", "--workspace",
                             str(workspace), "--output", "pilot.mlview.json"],
                            capture_output=True, text=True, check=False)
    assert json.loads(result.stdout)["ok"] is True, result.stdout + result.stderr


def fill_session(path: Path, *, status: str = "completed", failure: str = "") -> None:
    """The synthetic operator fills the session.md template that run-prepare wrote."""
    baseline = ":baseline:" in path.read_text(encoding="utf-8").split("\n", 1)[0]
    values = {"Status": status, "Failure": failure, "Started": STARTED, "Ended": ENDED, "Active minutes": "15",
              "Approval wait minutes": "0.5", "Repair rounds": "" if baseline else "1",
              "Host version": "synthetic-host 1.0 (synthetic)", "Extension version": "0.3.0", "Model": MODEL,
              "Reasoning": REASONING, "Resolved model": "unknown",
              "Invocation": "none (plain prompt; no skill) (synthetic)" if baseline else INVOCATION,
              "Helper Python": "" if baseline else "3.12.4", "Usage": "unknown"}
    out = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        key = line.split(":", 1)[0]
        if key in values and line in (f"{key}:", f"{key}: pending"):
            line = f"{key}: {values[key]}".rstrip()
        out.append(line)
    write_lf(path, "\n".join(out))


def fill_review(path: Path, overrides: dict | None = None) -> None:
    """The synthetic reviewer replaces every pending value of the review template."""
    overrides = overrides or {}
    lines = path.read_text(encoding="utf-8").split("\n")
    baseline = ":baseline:" in lines[0]
    out, section = [], "header"
    for line in lines:
        if line.startswith("## "):
            section = line[3:]
            out.append(line)
            if section == "Claims" and baseline:
                out.append("response:1-2: supported")
            continue
        if line == "Reviewer:":
            line = f"Reviewer: {REVIEWER}"
        elif line == "Date:":
            line = "Date: 2026-10-15"
        elif line == "Review: pending":
            line = "Review: complete"
        elif line.endswith(": pending"):
            key = line[:-len(": pending")]
            default = {"Claims": "supported", "Severity": "agree",
                       "Essential facts": "covered response:1-2" if baseline else "covered node:load",
                       "Known unresolved": "stated response:3" if baseline else "stated coverage",
                       "Usability": "useful" if key == "task" else "clear", "Reference defects": "missed"}[section]
            line = f"{key}: {overrides.get((section, key), default)}"
        out.append(line)
    write_lf(path, "\n".join(out))


def forget(world: World, run_id: str) -> None:
    """Fixture setup only: remove a run's evidence and its preparations.jsonl lines, as if it never ran."""
    shutil.rmtree(world.evidence(run_id))
    ledger = world.pilot_dir / wp.LEDGER_FILE
    lines = [line for line in ledger.read_text(encoding="utf-8").splitlines(keepends=True)
             if json.loads(line)["run"] != run_id]
    ledger.write_text("".join(lines), encoding="utf-8")


def do_run(world: World, run_id: str, *, status: str = "completed", failure: str = "", review: bool = True) -> None:
    code, out, err = pilot(world.clone, "run-prepare", run_id, *world.args())
    assert code == 0, out + err
    baseline = ":baseline:" in run_id
    evidence = world.evidence(run_id)
    if not baseline and status == "completed":
        publish(world, run_id)
    prompt = (evidence / "PROMPT.txt").read_text(encoding="utf-8")
    answer = "The loop runs forty steps.\nEach step updates the model.\nThe output contents are unknown.\n"
    write_lf(evidence / "transcript.txt", prompt + "\n" + answer)
    if not baseline:
        write_lf(evidence / "ui-log.md", "Synthetic UI checklist: opened, filtered, navigated.\n")
    fill_session(evidence / "session.md", status=status, failure=failure)
    code, out, err = pilot(world.clone, "run-finish", run_id, *world.args())
    assert code == 0, out + err
    assert not world.workspace(run_id).exists()
    if review and status == "completed":
        code, out, err = pilot(world.clone, "review-template", run_id, *world.args())
        assert code == 0, out + err
        fill_review(evidence / "review.md")


def stage1_ids() -> list[str]:
    return [f"{TASK}:{host}:1" for host in HOSTS] + [f"{TASK}:{host}:baseline:1" for host in HOSTS]


class Clock:
    def __init__(self) -> None:
        self.now = CAPTURED_AT

    def __call__(self) -> str:
        return self.now


def environment(patcher: pytest.MonkeyPatch, world: World, clock: Clock) -> None:
    for key in list(os.environ):
        if key.startswith("GIT_"):
            patcher.delenv(key)
    patcher.setenv("GIT_CONFIG_NOSYSTEM", "1")
    patcher.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    patcher.setenv("MLVIEW_PUBLIC_CORPUS_DIR", str(world.corpus))
    patcher.delenv("MLVIEW_PILOT_DIR", raising=False)
    patcher.setattr(er, "rfc3339_utc_now", clock)


def build(base: Path, patcher: pytest.MonkeyPatch, clock: Clock) -> World:
    """Run the whole owner and operator workflow up to reviewed Stage 1 runs, asserting each step."""
    world = World(base, base / "corpus", base / "work", base / "clone", base / "pilot")
    environment(patcher, world, clock)
    sha = make_corpus(world.corpus)
    make_mlview(world.work, sha)
    work, corpus = world.work, world.corpus
    assert fetch_workflow_repos.verify_repo(json.loads((work / wp.REPOSITORIES_REL).read_text(encoding="utf-8"))["repos"][0],
                                            corpus)["ok"] is True

    # template -> check (pending) -> synthetic decisions -> check (ready)
    for argv in (("template", TASK), ("template", TASK, "--second"), ("template", "run-policy")):
        code, out = decisions(work, corpus, *argv)
        assert code == 0 and "every value pending" in out, out
    code, out = decisions(work, corpus, "template", TASK)
    assert code == 1 and "templates are created exclusively and never overwritten" in out
    code, out = decisions(work, corpus, "check", TASK)
    assert code == 0 and f"{TASK}: 0 error(s)" in out and "in progress" in out, out
    pristine = (work / wd.DECISIONS_REL / f"{TASK}.md").read_text(encoding="utf-8")
    code, shown = decisions(work, corpus, "template", "--show", TASK)
    assert code == 0 and shown == pristine
    primary = primary_decisions(work)
    write_lf(work / wd.DECISIONS_REL / f"{TASK}.second.md", second_decisions(work))
    write_lf(work / wd.DECISIONS_REL / f"{TASK}.md", primary.replace("\nReview: pending\n", "\nReview: complete\n"))
    code, out = decisions(work, corpus, "check", TASK)
    assert code == 0 and "Disagreements: demo-f01: the second reviewer (Second Test Reviewer (synthetic)) chose " \
                         "reject; you chose accept" in out, out
    assert "TODO  Task: Review is complete, but the second review added 1 item(s) to resolve" in out, out
    resolved = primary.replace("## Disagreements\n", "## Disagreements\ndemo-f01: kept the accepted claim after "
                                                     "discussion (synthetic)\n")
    write_lf(work / wd.DECISIONS_REL / f"{TASK}.md", resolved.replace("\nReview: pending\n", "\nReview: complete\n"))
    write_lf(work / wd.DECISIONS_REL / "run-policy.md", policy_decisions(work))
    code, out = decisions(work, corpus, "check")
    assert code == 0, out
    assert f"{TASK}: 0 error(s), 0 to do; ready to freeze." in out
    assert f"{TASK} (second review): 0 error(s), 0 to do; ready to freeze." in out
    assert "run-policy: 0 error(s), 0 to do; ready to freeze." in out
    assert "anchors checked against demo@" in out
    code, out = decisions(work, corpus, "check", "run-policy", "--show-prompts")
    assert code == 0 and "Explain the synthetic training loop and its defaults." in out, out

    # freeze: dry run, then --write with a fixed time; check-frozen re-derives byte for byte
    before = (work / wp.TASKS_REL).read_bytes()
    code, out = decisions(work, corpus, "freeze", "--campaign", CAMPAIGN, "--frozen-at", FROZEN_AT)
    assert code == 0 and f"Ready to freeze {CAMPAIGN} (dry run; nothing written)" in out, out
    assert not (work / wp.PILOT_REL / CAMPAIGN).exists() and (work / wp.TASKS_REL).read_bytes() == before
    code, out = decisions(work, corpus, "freeze", "--campaign", CAMPAIGN, "--write", "--frozen-at", FROZEN_AT)
    assert code == 0 and "it does not add an approval" in out, out
    code, out = decisions(work, corpus, "check-frozen")
    assert code == 0 and "re-derived byte for byte" in out, out
    commit_all(work, "synthetic decisions and freeze")

    # capture the pilot candidate in a fresh clone of the frozen state (stub packager only)
    subprocess.run(["git", "clone", "--quiet", str(work), str(world.clone)], capture_output=True, env=git_env(),
                   check=True)
    target, record = wc.capture_pilot(CAMPAIGN, world.pilot_dir, world.clone, package=stub_package,
                                      check_frozen=real_check_frozen(corpus))
    assert target.resolve() == (world.campaign_dir() / "candidate.json").resolve()
    assert record["pilotApproved"] is False
    assert (world.pilot_dir / "mlview-0.3.0.vsix").is_file()
    commit_all(world.clone, "synthetic pilot candidate")
    assert wc.check(record, world.clone) == []
    clock.now = RUN_CLOCK

    # plan -> run-prepare -> the real helper publishes -> run-finish -> review-template -> review
    code, out, err = pilot(world.clone, "plan", "--campaign", CAMPAIGN, "--stage", "1")
    assert code == 0, err
    plan = json.loads(out)
    assert plan["frozen"] is True and [run["id"] for run in plan["runs"]] == stage1_ids()
    for run_id in stage1_ids():
        do_run(world, run_id)
    return world


@pytest.fixture(scope="module")
def base_world(tmp_path_factory) -> World:
    patcher = pytest.MonkeyPatch()
    try:
        world = build(tmp_path_factory.mktemp("pilot-e2e"), patcher, Clock())
        yield world
    finally:
        patcher.undo()


@pytest.fixture
def world(base_world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    target = tmp_path / "w"
    shutil.copytree(base_world.base, target, symlinks=True)
    copied = World(target, target / "corpus", target / "work", target / "clone", target / "pilot")
    clock = Clock()
    clock.now = SUMMARY_CLOCK
    environment(monkeypatch, copied, clock)
    return copied


def summarize(world: World, stage: str = "1") -> dict:
    code, out, err = pilot(world.clone, "summarize", "--stage", stage, "--json", *world.args())
    assert code == 0, err
    return json.loads(out)


def integrity_errors(world: World) -> str:
    code, out, err = pilot(world.clone, "summarize", "--stage", "1", *world.args())
    assert code == 1 and out == "" and "no decision was computed" in err, out + err
    return err


def review_line(world: World, run_id: str, old: str, new: str) -> None:
    path = world.evidence(run_id) / "review.md"
    text = path.read_text(encoding="utf-8")
    assert f"\n{old}\n" in text
    write_lf(path, text.replace(f"\n{old}\n", f"\n{new}\n", 1))


# --------------------------------------------------------------------------------------------
# The workflow end to end


def test_frozen_campaign_matches_the_decisions_and_carries_no_approval(world: World) -> None:
    campaign = world.campaign_dir()
    reference = json.loads((campaign / f"reference/{TASK}.json").read_text(encoding="utf-8"))
    assert reference["essentialFactIds"] == ["demo-f01", "demo-f02", "demo-h01"]
    assert [item["id"] for item in reference["knownUnresolved"] if item["runsMustState"]] == ["demo-u01"]
    assert [review["reviewer"] for review in reference["reviews"]] == [REVIEWER, SECOND]
    assert [dispute["item"] for dispute in reference["disputes"]] == ["demo-f01"]
    tasks = json.loads((world.clone / wp.TASKS_REL).read_text(encoding="utf-8"))
    freeze = json.loads((campaign / "freeze.json").read_text(encoding="utf-8"))
    candidate = json.loads((campaign / "candidate.json").read_text(encoding="utf-8"))
    revision = "sha256:" + er.sha256_file(campaign / "reference-set.json")
    assert tasks["pilotFreeze"] == {"campaign": CAMPAIGN, "freeze": f"pilot/{CAMPAIGN}/freeze.json",
                                    "referenceRevision": revision}
    assert freeze["referenceRevision"] == candidate["referenceRevision"] == revision
    assert [task["referenceStatus"] for task in tasks["tasks"]] == ["needs-human-review", "frozen"]
    assert candidate["pilotApproved"] is False and candidate["kind"] == "pilot-candidate"
    for path in sorted(campaign.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            assert no_machine_paths(data), path
            if path.suffix == ".json":
                assert data == er.canonical_json(json.loads(data)), path
    prompts = sorted(p.relative_to(campaign).as_posix() for p in (campaign / "prompts").rglob("*.txt"))
    assert prompts == [f"prompts/baseline/{TASK}.txt", f"prompts/skill/{TASK}.txt"]
    baseline = (campaign / f"prompts/baseline/{TASK}.txt").read_text(encoding="utf-8").casefold()
    assert "mlview" not in baseline and "workflowdocument" not in baseline


def test_run_records_are_sealed_and_owner_checks_route_to_the_pilot_checker(world: World) -> None:
    run_id = f"{TASK}:claude-code:1"
    evidence = world.evidence(run_id)
    record = json.loads((evidence / "record.json").read_text(encoding="utf-8"))
    assert record["format"] == "mlview-pilot-run/1" and record["id"] == run_id
    assert record["candidateSha256"] == er.sha256_file(world.campaign_dir() / "candidate.json")
    assert record["prompt"]["frozen"] == f"prompts/skill/{TASK}.txt"
    assert record["workspace"]["changedProjectFiles"] == [] and record["amendments"] == []
    assert no_machine_paths((evidence / "record.json").read_bytes())
    # The owner's `check` command routes session and run-review files to the pilot checker.
    for name, expected in (("session.md", "session.md: 0 error(s), 0 to do; complete."),
                           ("review.md", "review.md: 0 error(s), 0 to do; complete.")):
        code, out = decisions(world.clone, world.corpus, "check", str(evidence / name))
        assert code == 0 and expected in out, out
    review_line(world, run_id, "demo-f01: covered node:load", "demo-f01: covered node:nowhere")
    code, out = decisions(world.clone, world.corpus, "check", str(evidence / "review.md"))
    assert code == 1 and "node:nowhere" in out, out


def test_summarize_go_is_recorded_and_opens_stage_2(world: World) -> None:
    code, _out, err = pilot(world.clone, "run-prepare", f"{TASK}:codex:2", *world.args())
    assert code == 1 and "there is no committed stage1-summary.json" in err
    summary = summarize(world)
    decision = summary["decision"]
    assert decision["value"] == "go", decision
    assert decision["label"] == "computed against the predefined targets; not an approval"
    assert summary["pilotApproved"] is False and summary["verification"]["complete"] is True
    assert {target["key"]: target["met"] for target in summary["targets"]} == dict.fromkeys(TARGETS, True)
    recall = next(target for target in summary["targets"] if target["key"] == "essentialFactRecall")
    assert (recall["numerator"], recall["denominator"]) == (9, 9)
    assert summary["disputedEssentialFacts"] == [{"task": TASK, "item": "demo-f01"}]
    assert summary["baselines"] is not None and len(summary["runs"]) == len(HOSTS)
    code, out, err = pilot(world.clone, "summarize", "--stage", "1", "--record", *world.args())
    assert code == 0 and out.startswith(f"# MLView pilot {CAMPAIGN}") and "not an approval" in err, err
    recorded = world.campaign_dir() / "stage1-summary.json"
    markdown = (world.campaign_dir() / "stage1-summary.md").read_text(encoding="utf-8")
    assert markdown == wp.render_markdown(json.loads(recorded.read_bytes()))
    assert no_machine_paths(recorded.read_bytes()) and no_machine_paths(markdown)
    code, _out, err = pilot(world.clone, "summarize", "--stage", "1", "--record", *world.args())
    assert code == 1 and "never overwritten" in err
    for item in json.loads(recorded.read_bytes())["inputs"]["runs"]:  # review normalization v1 beside each review
        path = world.evidence(item["id"]) / "review.md"
        assert item["reviewNormalized"] == (None if item["review"] is None else
                                            {"version": 1, "sha256": er.normalized_review_sha256(path.read_bytes())})
    commit_all(world.clone, "synthetic Stage 1 summary")
    code, out = decisions(world.clone, world.corpus, "check-frozen")
    assert code == 0, out
    code, out, err = pilot(world.clone, "run-prepare", f"{TASK}:codex:2", *world.args())
    assert code == 0, err
    # A re-saved Stage 1 review (CRLF and a note) keeps its normalized hash; a changed verdict holds Stage 2.
    review = world.evidence(f"{TASK}:copilot:1") / "review.md"
    original = review.read_bytes()
    review.write_bytes(original.replace(b"\n", b"\r\n") + b"> a note added after the record (synthetic)\r\n")
    code, out, err = pilot(world.clone, "run-prepare", f"{TASK}:copilot:2", *world.args())
    assert code == 0, err
    review.write_bytes(original.replace(b"\ndemo-f02: covered", b"\ndemo-f02: missing", 1))
    assert review.read_bytes() != original
    code, out, err = pilot(world.clone, "run-prepare", f"{TASK}:claude-code:2", *world.args())
    assert code == 1 and f"{TASK}:copilot:1 (evidence/{TASK}.copilot.1/review.md) changed (normalized sha256" in err, err
    review.write_bytes(original)
    code, out, err = pilot(world.clone, "run-prepare", f"{TASK}:claude-code:2", *world.args())
    assert code == 0, err


# --------------------------------------------------------------------------------------------
# Mutations: stop, incomplete, invalid and integrity errors


def test_an_unsupported_high_severity_finding_stops_stage_1(world: World) -> None:
    review_line(world, f"{TASK}:codex:1", "finding:f1: supported",
                f"finding:f1: unsupported {EM} synthetic: the source does not show this")
    decision = summarize(world)["decision"]
    assert decision["value"] == "stop"
    assert any(reason.startswith("T6 highSeverityFalseAccusations: 1") for reason in decision["reasons"]), decision


def test_an_invalidating_deviation_amended_into_a_run_stops_stage_1(world: World) -> None:
    run_id = f"{TASK}:copilot:1"
    session = world.evidence(run_id) / "session.md"
    write_lf(session, session.read_text(encoding="utf-8").replace(
        "## Deviations\n", f"## Deviations\nThe synthetic operator reused an old chat {EM} invalidates: yes\n"))
    code, out, err = pilot(world.clone, "run-finish", run_id, *world.args(), "--amend", "synthetic amendment")
    assert code == 0, out + err
    assert (world.evidence(run_id) / "record.previous-1.json").is_file()
    summary = summarize(world)
    run = next(item for item in summary["runs"] if item["id"] == run_id)
    assert run["status"] == "invalid" and any("deviation" in reason for reason in run["invalidReasons"])
    assert summary["decision"]["value"] == "stop"
    assert any(reason.startswith("T1 structurallyValid: 2/3") for reason in summary["decision"]["reasons"])
    assert [entry["amendments"] for entry in summary["inputs"]["runs"] if entry["id"] == run_id][0]


def test_missing_reviews_and_runs_leave_stage_1_incomplete(world: World) -> None:
    (world.evidence(f"{TASK}:codex:1") / "review.md").unlink()
    decision = summarize(world)["decision"]
    assert decision["value"] == "incomplete" and any("unreviewed" in reason for reason in decision["reasons"])
    forget(world, f"{TASK}:copilot:1")
    do_run(world, f"{TASK}:copilot:1", status="failed", failure=f"no-publication {EM} synthetic failure")
    (world.evidence(f"{TASK}:claude-code:1") / "record.json").unlink()  # sealed evidence kept; the run is pending
    decision = summarize(world)["decision"]
    assert decision["value"] == "incomplete"
    assert any("pending" in reason for reason in decision["reasons"]), decision
    assert any(item.startswith("T1") and f"{TASK}:copilot:1" in item for item in decision["earlyStopIndicators"])


def test_an_owner_invalidation_makes_the_campaign_invalid(world: World) -> None:
    write_lf((world.campaign_dir() / "invalidation.md"), 
        f"# Invalidation: {CAMPAIGN}\nReviewer: {REVIEWER}\nDate: 2026-10-21\nScope: stage1\n"
        "Reason: synthetic invalidation for the end-to-end test\n")
    decision = summarize(world)["decision"]
    assert decision["value"] == "invalid" and "invalidation" in decision["reasons"][0]


def test_integrity_errors_refuse_a_decision(world: World) -> None:
    artifact = world.evidence(f"{TASK}:codex:1") / "artifact.mlview.json"
    artifact.write_bytes(artifact.read_bytes().replace(b"Synthetic finding", b"Edited finding!!"))
    (world.pilot_dir / "evidence" / f"{TASK}.codex.9").mkdir()
    err = integrity_errors(world)
    assert "evidence.artifact: artifact.mlview.json does not match its sealed SHA-256" in err
    assert f"{TASK}:codex:9 is not a planned run of {CAMPAIGN}" in err


def test_a_changed_candidate_record_breaks_the_chain(world: World) -> None:
    path = world.campaign_dir() / "candidate.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["source"]["capturedAt"] = "2026-10-02T09:00:01Z"
    path.write_bytes(er.canonical_json(value))
    err = integrity_errors(world)
    assert "candidateSha256: differs from sha256(candidate.json)" in err


def test_a_corpus_checkout_that_fails_verification_blocks_freeze_and_run_prepare(world: World) -> None:
    (world.corpus / "demo" / "train.py").write_bytes(DEMO_FILES["train.py"].encode("utf-8") + b"# edited\n")
    forget(world, f"{TASK}:codex:1")
    code, _out, err = pilot(world.clone, "run-prepare", f"{TASK}:codex:1", *world.args())
    assert code == 1 and "failed verification" in err and "differ from the pinned blobs" in err, err
    owner_world = wd.World(world.clone, world.corpus)
    problem = wd._verify_corpus(owner_world, owner_world.heldout_task(TASK))
    assert problem is not None and problem.startswith("the checkout failed verification (demo: the checkout has "
                                                      "local changes"), problem
    assert "demo: 1 file(s) differ from the pinned blobs (train.py)" in problem
