#!/usr/bin/env python3
"""Owner decision files for the held-out pilot: templates, checks, context sheets and the freeze.

Commands (dispatched by ``tools/workflow_eval.py``; ``main`` receives the command name first):

* ``template TARGET [--second] [--show]`` and ``template --init-all`` write pending templates for
  a held-out task, its second review, ``run-policy`` or ``development-adjudication``. Files are
  created exclusively and never overwritten; ``--show`` prints a pristine copy instead.
* ``check [TARGET ...] [--show-prompts]`` checks reference decisions, second reviews, the run
  policy and the development adjudication (session and run-review files go to
  ``tools/workflow_pilot.py``). It never writes. Each problem is printed as
  ``path:line: LEVEL section: message``; the exit status is 1 only when there are errors.
* ``context TASK`` writes a gitignored sheet under ``.mlview/review-context/`` that shows each
  candidate anchor's verified quote with numbered source context. It does not interpret code.
* ``freeze --campaign C [--write]`` derives the frozen campaign (references, reference set, run
  policy, 16 prompts, freeze.json) from completed decisions; a dry run unless ``--write``.
* ``check-frozen`` re-derives the committed frozen campaign and requires byte equality.

No code path here writes a decision, reviewer name, verdict, essential flag, policy value or
approval into an owner file: templates hold only ``pending`` values and empty names, and the
freeze refuses anything pending. The tool cannot authenticate a person; ``Transcribed by``,
commit authorship and the repository rules for agents are the safeguards. Local checks are not
semantic accuracy, human review or live-host validation.
"""
from __future__ import annotations

import argparse
import copy
import datetime as _dt
import importlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import eval_records as er  # noqa: E402

ROOT = TOOLS.parent
DECISIONS_REL = "evals/workflow/decisions"
CANDIDATES_REL = er.CANDIDATES_REL
TASKS_REL = er.TASKS_REL
REPOSITORIES_REL = "evals/workflow/repositories.json"
PILOT_REL = "evals/workflow/pilot"
DEVELOPMENT_REL = "evals/workflow/development"
CONTEXT_REL = ".mlview/review-context"
GUIDE_REL = "evals/workflow/reference-candidates/REVIEW_GUIDE.md"
CHECK_COMMAND = "python tools/workflow_eval.py check"
TEMPLATE_COMMAND = "python tools/workflow_eval.py template"
POLICY_TARGET = "run-policy"
ADJUDICATION_TARGET = "development-adjudication"
ARTIFACT_PATH = "pilot.mlview.json"
NOTE_TEXT = "Frozen from named human decisions; hashes identify bytes, not approval."
TOOLING_FILES = ("tools/workflow_decisions.py", "tools/eval_records.py", "skills/mlview/scripts/artifact.py")

DECISIONS = ("accept", "qualify", "reject")
SCENARIO_DECISIONS = ("accept", "replace")
BASES = ("observed", "inferred", "unresolved")
SEVERITIES = ("high", "medium", "low")
YES_NO = {"yes": True, "no": False}
USABILITY_ORDER = ("dataOrigin", "updatedParametersAndFitState", "losses", "evaluationBoundaries", "outputs",
                   "uncertainty")
USABILITY_VERDICTS = ("clear", "partial", "missing")
BASELINE_VERDICTS = ("confirmed", "corrected", "rejected")
QUALIFIED_CLAIMS = ("not-supported", "supported", "excluded")
ADJUDICATION_GATE = ("required", "not-required")
PLACEHOLDERS = ("task_prompt", "scenario", "artifact_path")
LEAK_MINIMUM = 30

MACHINE_PATH_RE = re.compile(r"/Users/|/home/|/private/|(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
PROPOSAL_PLACEHOLDER_RE = re.compile(r"<[^<>]+>")
PROMPT_PLACEHOLDER_RE = re.compile(r"\{([^{}\s]*)\}")
NO_SKILL_FORBIDDEN_RE = re.compile(r"mlview|workflowdocument|\.mlview\.json|\bskill\b", re.IGNORECASE)
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})", re.ASCII)
INTEGER_RE = re.compile(r"[0-9]+", re.ASCII)

_DEFAULT = object()
_PENDING = "pending"


class UsageError(Exception):
    """A command-line mistake (exit status 2)."""


# --------------------------------------------------------------------------------------------
# The world: an MLView checkout (real or synthetic) and an optional pinned corpus


def default_corpus(root: Path) -> Path | None:
    configured = os.environ.get("MLVIEW_PUBLIC_CORPUS_DIR")
    path = Path(configured).expanduser() if configured else Path(root) / ".public-corpus"
    return path if path.is_dir() else None


class World:
    """Everything a check or freeze reads. Tests pass a synthetic ``root`` and ``corpus``."""

    def __init__(self, root: Path = ROOT, corpus: object = _DEFAULT, decisions_dir: Path | None = None) -> None:
        self.root = Path(root)
        self.decisions_dir = Path(decisions_dir) if decisions_dir is not None else self.root / DECISIONS_REL
        if corpus is _DEFAULT:
            corpus = default_corpus(self.root)
        self.corpus = Path(corpus) if corpus is not None and Path(corpus).is_dir() else None
        self._manifest: tuple[bytes, dict] | None = None
        self._repositories: tuple[bytes, dict] | None = None
        self._ledgers: dict[str, tuple[dict, bytes]] = {}
        self._trees: dict[str, dict[str, str] | Exception] = {}
        self._bytes: dict[tuple[str, str], bytes | Exception] = {}
        self._helper = None

    # -- manifests
    def manifest_bytes(self) -> bytes:
        return self._load_manifest()[0]

    @property
    def manifest(self) -> dict:
        return self._load_manifest()[1]

    def _load_manifest(self) -> tuple[bytes, dict]:
        if self._manifest is None:
            raw = (self.root / TASKS_REL).read_bytes()
            self._manifest = (raw, json.loads(raw.decode("utf-8")))
        return self._manifest

    def reload_manifest(self) -> None:
        self._manifest = None

    @property
    def repositories(self) -> dict:
        if self._repositories is None:
            raw = (self.root / REPOSITORIES_REL).read_bytes()
            self._repositories = (raw, json.loads(raw.decode("utf-8")))
        return self._repositories[1]

    def repositories_bytes(self) -> bytes:
        self.repositories  # noqa: B018 - loads the cache
        assert self._repositories is not None
        return self._repositories[0]

    @property
    def hosts(self) -> list[str]:
        return list(self.manifest.get("hosts") or [])

    @property
    def heldout(self) -> list[dict]:
        return [task for task in self.manifest.get("tasks") or [] if task.get("split") == "heldout"]

    def heldout_task(self, task_id: str | None) -> dict | None:
        return next((task for task in self.heldout if task.get("id") == task_id), None)

    def ledger(self, task_id: str) -> tuple[dict, bytes]:
        if task_id not in self._ledgers:
            raw = (self.root / CANDIDATES_REL / f"{task_id}.json").read_bytes()
            self._ledgers[task_id] = (json.loads(raw.decode("utf-8")), raw)
        return self._ledgers[task_id]

    def repo_entry(self, task: dict) -> dict | None:
        return next((repo for repo in self.repositories.get("repos") or []
                     if repo.get("name") == task.get("repository")), None)

    # -- corpus
    def repo_dir(self, task: dict) -> Path | None:
        if self.corpus is None or not isinstance(task.get("repository"), str):
            return None
        path = self.corpus / task["repository"]
        return path if path.is_dir() else None

    def tree(self, task: dict) -> dict[str, str] | None:
        """The pinned tree of the task's repository, or None when the corpus is absent. Raises
        ValueError when the checkout is present but its pinned tree cannot be read."""
        repo = self.repo_dir(task)
        if repo is None:
            return None
        key = task["id"]
        if key not in self._trees:
            try:
                self._trees[key] = er.pinned_tree(repo, task["commit"])
            except ValueError as exc:
                self._trees[key] = exc
        value = self._trees[key]
        if isinstance(value, Exception):
            raise value
        return value

    def pinned(self, task: dict, path: str) -> bytes:
        """Materialised, blob-exact bytes of ``path`` at the task's pinned commit (ValueError)."""
        key = (task["id"], path)
        if key not in self._bytes:
            try:
                repo = self.repo_dir(task)
                if repo is None:
                    raise ValueError("the corpus is absent")
                self._bytes[key] = er.pinned_bytes(repo, task["commit"], path, tree=self.tree(task))
            except ValueError as exc:
                self._bytes[key] = exc
        value = self._bytes[key]
        if isinstance(value, Exception):
            raise value
        return value

    @property
    def helper(self):
        if self._helper is None:
            self._helper = er.load_helper()
        return self._helper

    def display(self, path: Path) -> str:
        path = Path(path)
        try:
            return path.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return str(path)

    def corpus_display(self, task: dict) -> str:
        repo = self.repo_dir(task)
        return self.display(repo) if repo is not None else "-"


def short_name(task_id: str) -> str:
    return task_id[len("pilot-"):] if task_id.startswith("pilot-") else task_id


def one_line(text: object) -> str:
    return " ".join(str(text).split())


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _locator(anchor: dict) -> str:
    return er.format_anchor(anchor["file"], anchor.get("cell"), anchor["line"], anchor["endLine"])


def unknown_ids(task_id: str, ledger: dict) -> list[str]:
    return [f"{short_name(task_id)}-u{index:02d}" for index in range(1, len(ledger.get("unknowns") or []) + 1)]


def nondefect_ids(task_id: str, ledger: dict) -> list[str]:
    return [f"{short_name(task_id)}-n{index:02d}" for index in range(1, len(ledger.get("nonDefects") or []) + 1)]


def added_patterns(task_id: str) -> dict[str, str]:
    """The exact ID pattern of each owner-added section kind of a task."""
    short = re.escape(short_name(task_id))
    return {"Added fact": rf"{short}-h\d{{2}}", "Added unknown": rf"{short}-hu\d{{2}}", "Defect": rf"{short}-d\d{{2}}"}


# --------------------------------------------------------------------------------------------
# Templates (only pending values and empty names are ever written)


def task_template(world: World, task_id: str, *, second: bool = False) -> str:
    ledger, raw = world.ledger(task_id)
    short = short_name(task_id)
    scenario = ledger["scenario"]
    if second:
        lines = [f"# Second review: {task_id}", "",
                 f"> Guide: {GUIDE_REL}. Check: {CHECK_COMMAND} {task_id}",
                 '> Second review: decide any subset of items; "pending" means not reviewed. Only a person may be a second reviewer.',
                 '> Fact and Non-defect: Decision: accept | qualify | reject. Unknown: the same, plus "Runs must state: yes | no" unless rejected.',
                 '> qualify = accept with your wording: add "Wording:" and "Reason:". reject: add "Reason:".',
                 '> To change a proposed Basis, Essential flag or Anchors, add that line and a "Reason:".']
    else:
        lines = [f"# Reference decisions: {task_id}", "",
                 f"> Guide: {GUIDE_REL}. Check: {CHECK_COMMAND} {task_id}",
                 '> Lines starting with ">" are written by the tool and ignored. Replace each "pending".',
                 '> Fact and Non-defect: Decision: accept | qualify | reject. Unknown: the same, plus "Runs must state: yes | no" unless rejected.',
                 '> qualify = accept with your wording: add "Wording:" and "Reason:". reject: add "Reason:".',
                 '> To change a proposed Basis, Essential flag or Anchors, add that line and a "Reason:".']
    lines += ["", f"Candidate: {task_id}.json {er.sha256_bytes(raw)}", "Reviewer:", "Date:", "Transcribed by:", "",
              "## Scenario",
              f"> Proposed: {one_line(scenario['description'])}",
              f"> Entrypoints: {'; '.join(scenario['entrypoints'])}",
              f"> Arguments: {'; '.join(scenario['arguments']) or 'none'}",
              "> accept, or replace and also write Description, Entrypoints, Arguments and Reason",
              "Decision: pending", ""]
    for fact in ledger["facts"]:
        lines += [f"## Fact {fact['id']}", f"> Claim: {one_line(fact['claim'])}",
                  f"> Basis: {fact['basis']}. Essential: {_yes_no(fact['essential'])}. "
                  f"Anchors: {'; '.join(_locator(anchor) for anchor in fact['anchors'])}",
                  "Decision: pending", ""]
    for ident, text in zip(unknown_ids(task_id, ledger), ledger["unknowns"]):
        lines += [f"## Unknown {ident}", f"> {one_line(text)}", "Decision: pending", "Runs must state:", ""]
    for ident, text in zip(nondefect_ids(task_id, ledger), ledger["nonDefects"]):
        lines += [f"## Non-defect {ident}", f"> {one_line(text)}", "Decision: pending", ""]
    lines += [f'> Omitted fact: add "## Added fact {short}-h01" with Wording, Basis, Essential, Anchors and Reason.',
              f'> Omitted unknown: add "## Added unknown {short}-hu01" with Wording, Runs must state and Reason.',
              f'> Real defect: add "## Defect {short}-d01" with Wording, Severity, Anchors, Counter-evidence and Reason.',
              ""]
    if not second:
        lines += ["## Disagreements",
                  '> Only when a second reviewer disagrees: one line "<item id>: <how it was resolved>".', ""]
    closing = "your decisions above are final" if second else "every decision above is final"
    lines += ["## Task", f'> Write "Review: complete" when {closing}.', "Review: pending", ""]
    return "\n".join(lines)


_HOST_NOTES = {
    "copilot": "Development runs: Copilot Auto, routed to GPT-5.6 Luna (a hidden resolved model stays unknown).",
    "codex": "Development runs: GPT-5.6 Sol, Ultra reasoning; invoked with the $mlview prefix.",
    "claude-code": "Development runs: Fable 5.1, Extra High reasoning.",
}

SKILL_PROMPT_PROPOSAL = (
    "{task_prompt}\n\nSelected scenario:\n{scenario}\n\n"
    "Inspect source without importing or executing target code. Read only this workspace and the installed skill; "
    "do not inspect parent folders, other workspaces or earlier artifacts. Use this assistant as the interpretation "
    "backend; do not delegate to subagents. Publish one WorkflowDocument to {artifact_path} using the installed "
    "helper, then report its path, revision, unresolved cases and repair rounds.")
NO_SKILL_PROMPT_PROPOSAL = (
    "{task_prompt}\n\nSelected scenario:\n{scenario}\n\n"
    "Inspect source without importing or executing target code. Read only this workspace; do not inspect parent "
    "folders or other workspaces. Do not delegate to subagents. Answer in this conversation: describe the workflow, "
    "the unresolved cases, and the files you inspected.")


def _target_text(key: str, value: object) -> str:
    if key == "highSeverityFalseAccusations":
        return f"{key} {value}"
    percent = f"{float(value) * 100:g}%"
    return f"{key} {percent}" if float(value) >= 1 else f"{key} >= {percent}"


def baseline_session_count(world: World) -> int:
    return len(world.heldout) * len(world.hosts)


def policy_template(world: World) -> str:
    targets = world.manifest.get("pilotTargets") or {}
    parts = [_target_text(key, targets.get(key)) for key in er.PILOT_TARGET_KEYS]
    lines = ["# Pilot run policy", "",
             f'> Guide: REVIEW_GUIDE.md, "Run policy". Check: {CHECK_COMMAND} {POLICY_TARGET}', "",
             "Reviewer:", "Date:", "Transcribed by:", ""]
    for host in world.hosts:
        lines += [f"## Host {host}", f"> {_HOST_NOTES.get(host, 'Development runs: not recorded for this host.')}",
                  "Model:", "Reasoning:", "Invocation:", ""]
    lines += ["## Environment",
              '> The skill runs "python3 <skill>/scripts/artifact.py". Each host\'s terminal must resolve python3 to 3.10+',
              "> (macOS /usr/bin/python3 is 3.9). Say how, without a machine path; it is not put into the prompt.",
              "Helper Python:", "",
              "## Budget",
              "> Proposed: 20 active minutes including critique and repair; at most 2 validator repair rounds;",
              "> 0 infrastructure retries (a retry is allowed only if the prompt was never sent).",
              "Active minutes:", "Repair rounds:", "Infrastructure retries:", "",
              "## Scoring",
              "> Qualified claims in supported-claim precision: not-supported | supported | excluded (CANDIDATE_PROTOCOL.md:56-59).",
              "> Per-host targets: yes = precision and recall must also meet their targets within each host; no = pooled only.",
              "Qualified claims:", "Per-host targets:", "",
              "## Conditions",
              f"> Baseline sessions: {baseline_session_count(world)} (one no-skill session per task and host, Stage 1 only) | 0.",
              "> Development adjudication before Stage 1: required | not-required.",
              "Baseline sessions:", "Development adjudication before Stage 1:", "",
              "## Targets",
              f"> {', '.join(parts[:4])},",
              f"> {', '.join(parts[4:])} (tasks.json pilotTargets). accept confirms them.",
              "Decision: pending", "",
              "## Skill prompt",
              "> Placeholders: {task_prompt} {scenario} {artifact_path}. The host's Invocation is sent before this text.",
              "```text", *SKILL_PROMPT_PROPOSAL.split("\n"), "```", "Decision: pending", "",
              "## No-skill prompt",
              "> Must not mention MLView, the skill, WorkflowDocument or publication (CANDIDATE_PROTOCOL.md:43-44).",
              "```text", *NO_SKILL_PROMPT_PROPOSAL.split("\n"), "```", "Decision: pending", "",
              "## Privacy",
              "> Raw transcripts, UI logs, run reviews and workspaces never enter the repository; committed summaries contain",
              "> counts, statuses and hashes only. Say what else, if anything, may be published.",
              "Publication:", "",
              "## Task", "Review: pending", ""]
    return "\n".join(lines)


def _workflow_eval():
    return _sibling("workflow_eval", required=True)


def adjudication_ledgers(world: World) -> list[tuple[str, str, str]]:
    """(task, host, path relative to evals/workflow/development) for the 12 native ledgers."""
    tasks = _workflow_eval().DEVELOPMENT_TASKS
    return [(task, host, f"native-reviews/{host}/{task}.json") for task in tasks for host in world.hosts]


def _development_json(world: World, rel: str) -> tuple[dict, bytes]:
    raw = (world.root / DEVELOPMENT_REL / rel).read_bytes()
    return json.loads(raw.decode("utf-8")), raw


def _development_rel(value: str) -> str:
    prefix = DEVELOPMENT_REL + "/"
    return value[len(prefix):] if isinstance(value, str) and value.startswith(prefix) else str(value)


def adjudication_template(world: World) -> str:
    lines = ["# Development adjudication", "",
             "> Human verdicts on the 12 provisional native reviews and 3 baseline notes; the ledgers are never edited.",
             "> Claims: supported | qualified | unsupported | omitted. Usability: clear | partial | missing.",
             '> Baselines: confirmed | corrected | rejected. Add " — <reason>" whenever you differ from the provisional',
             "> label, and for every baseline verdict except confirmed. Source context: the review packet (review-packet).",
             f"> Check: {CHECK_COMMAND} {ADJUDICATION_TARGET}", "",
             "Reviewer:", "Date:", "Transcribed by:", ""]
    for task, host, rel in adjudication_ledgers(world):
        ledger, raw = _development_json(world, rel)
        lines += [f"## {task} / {host}", f"Ledger: {rel} {er.sha256_bytes(raw)}",
                  f"> Artifact: {_development_rel(ledger.get('artifact'))} ({ledger.get('artifactRevision')})"]
        for claim in ledger["claims"]:
            lines += [f"> {claim['id']} (provisional: {claim['verdict']}): {one_line(claim['summary'])}",
                      f"{claim['id']}: pending"]
        for question in USABILITY_ORDER:
            answer = ledger["usability"][question]
            lines += [f"> usability.{question} (provisional: {answer['status']}): {one_line(answer['answer'])}",
                      f"usability.{question}: pending"]
        lines.append("")
    baselines, raw = _development_json(world, "native-reviews/baselines.json")
    by_host = {item.get("host"): item for item in baselines.get("baselines") or []}
    lines += ["## Baselines", f"Ledger: native-reviews/baselines.json {er.sha256_bytes(raw)}"]
    for host in world.hosts:
        item = by_host.get(host) or {}
        lines += [f"> {host} (provisional): {one_line(item.get('summary', ''))}", f"{host}: pending"]
    lines += ["", "## Task", "Review: pending", ""]
    return "\n".join(lines)


README_TEXT = """# Owner decisions

These files hold the pilot owner's reference decisions, second reviews, run policy and development adjudication. Every value starts as `pending`; only the named human reviewer replaces it.
Read the [review guide](../reference-candidates/REVIEW_GUIDE.md) first; `python tools/workflow_eval.py template --show <task>` prints a pristine copy of any file.
Check a file with `python tools/workflow_eval.py check <task>` (or `run-policy`, `development-adjudication`); the check never writes and ends with "ready to freeze" when a file is complete.
`python tools/workflow_eval.py freeze --campaign <name>` copies completed decisions into `evals/workflow/pilot/<name>/`; it records the reviewers' decisions and adds no approval.
"""


def template_targets(world: World) -> dict[str, tuple[Path, Callable[[], str]]]:
    """Every committed owner file: name -> (path, generator)."""
    targets: dict[str, tuple[Path, Callable[[], str]]] = {}
    for task in world.heldout:
        task_id = task["id"]
        targets[task_id] = (world.decisions_dir / f"{task_id}.md", lambda t=task_id: task_template(world, t))
    targets[POLICY_TARGET] = (world.decisions_dir / f"{POLICY_TARGET}.md", lambda: policy_template(world))
    targets[ADJUDICATION_TARGET] = (world.decisions_dir / f"{ADJUDICATION_TARGET}.md", lambda: adjudication_template(world))
    return targets


# --------------------------------------------------------------------------------------------
# Problems


LEVEL_ORDER = {er.ERROR: 0, er.TODO: 1, er.NOTE: 2}


class Report:
    def __init__(self, display: str) -> None:
        self.display = display
        self.problems: list[er.Problem] = []

    def add(self, line: int, level: str, section: str, message: str) -> None:
        self.problems.append(er.Problem(self.display, line, level, section, message))

    def error(self, line: int, section: str, message: str) -> None:
        self.add(line, er.ERROR, section, message)

    def todo(self, line: int, section: str, message: str) -> None:
        self.add(line, er.TODO, section, message)

    def note(self, line: int, section: str, message: str) -> None:
        self.add(line, er.NOTE, section, message)

    def count(self, level: str) -> int:
        return sum(1 for problem in self.problems if problem.level == level)

    @property
    def errors(self) -> int:
        return self.count(er.ERROR)

    @property
    def todos(self) -> int:
        return self.count(er.TODO)

    def ordered(self) -> list[er.Problem]:
        return sorted(self.problems, key=lambda problem: (problem.line, LEVEL_ORDER.get(problem.level, 9)))


def state_text(errors: int, todos: int, ready: str = "ready to freeze") -> str:
    if errors:
        return "not ready (fix the errors)"
    return "in progress" if todos else ready


def _value(section: er.Section | None, key: str) -> str:
    if section is None:
        return ""
    found = section.field(key)
    return found.value.strip() if found is not None else ""


def _field_line(section: er.Section, key: str) -> int:
    found = section.field(key)
    return found.line if found is not None else section.line


def _machine_path(text: str) -> str | None:
    match = MACHINE_PATH_RE.search(text or "")
    return match.group(0) if match else None


def _join_names(names: Sequence[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _valid_date(text: str) -> bool:
    match = DATE_RE.fullmatch(text)
    if not match:
        return False
    try:
        _dt.date(int(match[1]), int(match[2]), int(match[3]))
    except ValueError:
        return False
    return True


def _reviewer_header(report: Report, record: er.Record, *, who: str = "the person who checked the source") -> None:
    header = record.header
    for key, message in (("Reviewer", f"Reviewer is empty. Write the name of {who}."),
                         ("Date", "Date is empty. Write the review date as YYYY-MM-DD.")):
        found = header.field(key)
        if found is None or not found.value.strip():
            report.todo(found.line if found else header.line, "header", message)
    date = header.field("Date")
    if date is not None and date.value.strip() and not _valid_date(date.value.strip()):
        report.error(date.line, "header", f'"{date.value.strip()}" is not a date. Use YYYY-MM-DD.')
    transcribed = header.field("Transcribed by")
    if transcribed is not None and transcribed.value.strip():
        report.note(transcribed.line, "header", f"transcribed by {transcribed.value.strip()}; the reviewer must read "
                                                 'the whole file before writing "Review: complete".')


def _task_section(report: Report, record: er.Record, *, closing: str) -> str | None:
    """Check ``## Task`` after every other problem is known; returns the review state."""
    section = record.section("Task")
    if section is None:
        return None
    found = section.field("Review")
    value = found.value.strip().casefold() if found is not None else ""
    open_items = report.todos
    if value == "complete":
        if open_items:
            report.error(found.line, "Task", f"Review is complete, but {open_items} item(s) above are still to do.")
        return "complete"
    if value not in ("", "pending"):
        report.error(found.line, "Task", f'"Review: {found.value.strip()}" must be pending or complete.')
        return None
    report.todo(found.line if found else section.line, "Task",
                f'Review is not complete. Write "Review: complete" when {closing}.')
    return "pending"


def _missing_sections(report: Report, record: er.Record, expected: Iterable[tuple[str, str | None]], command: str) -> None:
    present = {(section.kind, section.ident) for section in record.sections}
    for kind, ident in expected:
        if (kind, ident) not in present:
            label = kind if ident is None else f"{kind} {ident}"
            report.error(1, label, f"this section is missing; restore it from the template ({command}).")


# --------------------------------------------------------------------------------------------
# Reference decisions and second reviews


@dataclass
class RefCheck:
    """The result of checking one reference-decisions or second-review file."""

    task_id: str | None
    role: str
    display: str
    report: Report
    record: er.Record | None = None
    reviewer: str = ""
    date: str = ""
    transcribed_by: str = ""
    review: str | None = None
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(DECISIONS, 0))
    essential_so_far: list[str] = field(default_factory=list)
    scenario: dict | None = None
    facts: list[dict] = field(default_factory=list)
    rejected_facts: list[dict] = field(default_factory=list)
    unknowns: list[dict] = field(default_factory=list)
    rejected_unknowns: list[dict] = field(default_factory=list)
    nondefects: list[dict] = field(default_factory=list)
    rejected_nondefects: list[dict] = field(default_factory=list)
    defects: list[dict] = field(default_factory=list)
    positions: dict[str, dict] = field(default_factory=dict)
    disputes: list[dict] = field(default_factory=list)
    added_facts: int = 0
    decided: int = 0
    items: int = 0
    corpus_checked: bool = False
    corpus_note: str = ""
    second: "RefCheck | None" = None

    @property
    def errors(self) -> int:
        return self.report.errors

    @property
    def todos(self) -> int:
        return self.report.todos

    @property
    def ready(self) -> bool:
        return self.record is not None and not self.errors and not self.todos and self.review == "complete"

    @property
    def name(self) -> str:
        base = self.task_id or Path(self.display).name
        return f"{base} (second review)" if self.role == "second" else base


class _RefChecker:
    def __init__(self, world: World, record: er.Record, report: Report, result: RefCheck, task: dict,
                 second: RefCheck | None) -> None:
        self.world, self.record, self.report, self.result, self.task = world, record, report, result, task
        self.second = second
        self.task_id: str = task["id"]
        self.short = short_name(self.task_id)
        self.primary = result.role == "primary"
        self.ledger, self.ledger_raw = world.ledger(self.task_id)
        self.facts = {fact["id"]: fact for fact in self.ledger["facts"]}
        self.unknown_text = dict(zip(unknown_ids(self.task_id, self.ledger), self.ledger["unknowns"]))
        self.nondefect_text = dict(zip(nondefect_ids(self.task_id, self.ledger), self.ledger["nonDefects"]))
        self.repo = world.repo_entry(task)
        self.repo_name = task.get("repository", "?")
        self.commit = task.get("commit", "")
        self.patterns: list[str] | None = None
        self.tree: dict[str, str] | None = None
        self.tree_error: str | None = None
        self.pattern_error: str | None = None
        try:
            self.patterns = list(self.repo.get("sparse", [])) if self.repo else None
            if self.patterns is not None:
                er.validate_sparse_patterns(self.patterns)
        except ValueError as exc:
            self.pattern_error, self.patterns = str(exc), None
        try:
            self.tree = world.tree(task)
        except ValueError as exc:
            self.tree_error = str(exc)
        result.corpus_checked = self.tree is not None
        if self.repo is None:
            self.pattern_error = f"{self.repo_name} is not listed in {REPOSITORIES_REL}"

    # -- helpers
    def label(self, section: er.Section) -> str:
        return section.label

    def has(self, section: er.Section, key: str) -> bool:
        return bool(_value(section, key))

    def decision(self, section: er.Section, allowed: Sequence[str]) -> str | None:
        found = section.field("Decision")
        label = self.label(section)
        if found is None:
            self.report.error(section.line, label, 'the "Decision:" line is missing.')
            return None
        value = found.value.strip().casefold()
        if value in ("", _PENDING):
            if self.primary:
                self.report.todo(found.line, label, "Decision is still pending.")
            return _PENDING
        if value not in allowed:
            self.report.error(found.line, label,
                              f'"Decision: {found.value.strip()}" is not a decision. Write one of: {", ".join(allowed)}.')
            return None
        return value

    def covered(self, path: str) -> bool | None:
        if self.patterns is None:
            return None
        return er.sparse_covers(self.patterns, path)

    def not_fetched(self, path: str) -> str:
        return (f"{path} is not fetched by repositories.json ({self.repo_name} sparse list); ask the maintainer to "
                "add it before freezing.")

    def check_path(self, line: int, label: str, path: str) -> bool:
        """Report a source path that is malformed, outside the pinned tree or not fetched."""
        problem = er._path_problem(path)
        if problem:
            self.report.error(line, label, f'"{path}" {problem}.')
            return False
        if self.tree is not None and path not in self.tree:
            self.report.error(line, label, f"{path} is not in the pinned {self.repo_name} tree at {self.commit[:12]}.")
            return False
        if self.covered(path) is False:
            self.report.error(line, label, self.not_fetched(path))
            return False
        return True

    def check_location(self, line: int, label: str, path: str, cell: int | None, start: int, end: int) -> None:
        if not self.check_path(line, label, path) or self.tree is None:
            return
        try:
            data = self.world.pinned(self.task, path)
        except ValueError as exc:
            self.report.error(line, label, f"cannot read {path}: {exc}.")
            return
        helper = self.world.helper
        if cell is not None:
            try:
                notebook = helper._parse_notebook(helper._strip_bom(data.decode("utf-8")))
            except UnicodeDecodeError:
                notebook = None
            cells = notebook.get("cells") if isinstance(notebook, dict) else None
            if not isinstance(cells, list):
                self.report.error(line, label, f"{path} is not a readable notebook.")
                return
            if cell >= len(cells):
                self.report.error(line, label, f"{path} has no cell{cell}.")
                return
        try:
            lines = er.source_lines(data, cell, helper)
        except ValueError as exc:
            where = f"{path}#cell{cell}" if cell is not None else path
            self.report.error(line, label, f"{where} cannot be read: {exc}.")
            return
        count = er.human_line_count(lines)
        if end > count:
            where = f"{path}#cell{cell}" if cell is not None else path
            self.report.error(line, label, f"{where} has {count} lines; line {end} is out of range.")

    def anchor_list(self, section: er.Section) -> list[tuple[str, int | None, int, int]] | None:
        found = section.field("Anchors")
        assert found is not None
        label = self.label(section)
        parsed: list[tuple[str, int | None, int, int]] = []
        failed = False
        for part in er.split_list(found.value):
            try:
                location = er.parse_anchor(part)
            except ValueError as exc:
                self.report.error(found.line, label, str(exc))
                failed = True
                continue
            if location in parsed:
                self.report.error(found.line, label, f'"{part}" is listed twice.')
                continue
            self.check_location(found.line, label, *location)
            parsed.append(location)
        return None if failed else parsed

    def basis(self, section: er.Section) -> str | None:
        found = section.field("Basis")
        value = found.value.strip().casefold() if found is not None else ""
        if not value:
            return None
        if value not in BASES:
            self.report.error(found.line, self.label(section),
                              f'"Basis: {found.value.strip()}" must be observed, inferred or unresolved.')
            return None
        return value

    def yes_no(self, section: er.Section, key: str) -> bool | None:
        found = section.field(key)
        value = found.value.strip().casefold() if found is not None else ""
        if not value:
            return None
        if value not in YES_NO:
            self.report.error(found.line, self.label(section), f'"{key}: {found.value.strip()}" must be yes or no.')
            return None
        return YES_NO[value]

    def reason(self, section: er.Section) -> str | None:
        return _value(section, "Reason") or None

    # -- sections
    def run(self) -> None:
        record, report, result = self.record, self.report, self.result
        candidate = record.header.field("Candidate")
        expected = f"{self.task_id}.json {er.sha256_bytes(self.ledger_raw)}"
        if candidate is None or " ".join(candidate.value.split()) != expected:
            report.error(candidate.line if candidate else record.header.line, "header",
                         f'the Candidate line must read "{self.task_id}.json {er.sha256_bytes(self.ledger_raw)[:12]}..."; '
                         "restore the line the tool wrote (candidate ledgers are immutable).")
        _reviewer_header(report, record)
        result.reviewer = _value(record.header, "Reviewer")
        result.date = _value(record.header, "Date")
        result.transcribed_by = _value(record.header, "Transcribed by")
        if self.pattern_error:
            report.error(record.header.line, "header", f"{REPOSITORIES_REL}: {self.pattern_error}")
        if self.tree_error:
            report.error(record.header.line, "header",
                         f"cannot read the pinned tree of {self.repo_name}: {self.tree_error}")
        command = f"{TEMPLATE_COMMAND} --show {self.task_id}{' --second' if not self.primary else ''}"
        expected_items = ([("Scenario", None)] + [("Fact", ident) for ident in self.facts]
                          + [("Unknown", ident) for ident in self.unknown_text]
                          + [("Non-defect", ident) for ident in self.nondefect_text])
        result.items = len(expected_items)
        if self.primary:
            _missing_sections(report, record, expected_items + [("Disagreements", None), ("Task", None)], command)
        else:
            _missing_sections(report, record, [("Task", None)], command)
        known = {"Fact": self.facts, "Unknown": self.unknown_text, "Non-defect": self.nondefect_text}
        handlers = {"Scenario": self.scenario, "Fact": self.fact, "Unknown": self.unknown,
                    "Non-defect": self.nondefect, "Added fact": self.added_fact,
                    "Added unknown": self.added_unknown, "Defect": self.defect}
        for section in record.sections:
            if section.kind in known and section.ident not in known[section.kind]:
                report.error(section.line, section.label,
                             f'"{section.ident}" is not an item of {self.task_id}.json. Added items use '
                             f'"## Added fact {self.short}-h01".')
                continue
            handler = handlers.get(section.kind)
            if handler is not None:
                handler(section)
        if self.primary:
            self.disagreements()
        result.review = _task_section(report, record,
                                      closing="your decisions above are final" if not self.primary
                                      else "every decision above is final")

    def position(self, ident: str, value: dict) -> None:
        self.result.positions[ident] = value
        self.result.decided += 1

    def scenario(self, section: er.Section) -> None:
        label = self.label(section)
        decision = self.decision(section, SCENARIO_DECISIONS)
        if decision in (None, _PENDING):
            return
        proposal = self.ledger["scenario"]
        decision_line = _field_line(section, "Decision")
        if decision == "accept":
            for key in ("Description", "Entrypoints", "Arguments", "Reason"):
                if self.has(section, key):
                    self.report.error(_field_line(section, key), label, f'{key} is used only with "Decision: replace".')
            if any(PROPOSAL_PLACEHOLDER_RE.search(argument) for argument in proposal["arguments"]):
                self.report.error(decision_line, label, 'the proposed arguments contain a placeholder (<...>); write '
                                                        '"Decision: replace" and give concrete Arguments.')
            effective = {"decision": "accept", "description": proposal["description"],
                         "entrypoints": list(proposal["entrypoints"]), "arguments": list(proposal["arguments"]),
                         "reason": None}
            self.scenario_paths(label, effective, decision_line, decision_line)
        else:
            for key in ("Description", "Entrypoints", "Arguments", "Reason"):
                if not self.has(section, key):
                    self.report.error(decision_line, label, f'Decision is replace but "{key}:" is missing or empty.')
            for key in ("Description", "Entrypoints", "Arguments"):
                machine = _machine_path(_value(section, key))
                if machine:
                    self.report.error(_field_line(section, key), label,
                                      f"{key} contains an absolute machine path ({machine}); use paths relative to "
                                      "the repository.")
            entrypoints = er.split_list(_value(section, "Entrypoints"))
            if self.has(section, "Entrypoints") and not entrypoints:
                self.report.error(_field_line(section, "Entrypoints"), label,
                                  'Entrypoints needs at least one path ("none" is only for Arguments).')
            effective = {"decision": "replace", "description": _value(section, "Description"),
                         "entrypoints": entrypoints, "arguments": er.split_list(_value(section, "Arguments")),
                         "reason": self.reason(section)}
            self.scenario_paths(label, effective, _field_line(section, "Entrypoints"), _field_line(section, "Arguments"))
        self.result.scenario = effective
        self.position("scenario", {"decision": decision})

    def scenario_paths(self, label: str, scenario: dict, entry_line: int, argument_line: int) -> None:
        for path in scenario["entrypoints"]:
            self.check_path(entry_line, label, path)
        if self.tree is None:
            return
        listed = set(scenario["entrypoints"])
        reported: set[str] = set()
        for argument in scenario["arguments"]:
            for token in _argument_tokens(argument):
                if token in self.tree and token not in listed and token not in reported:
                    reported.add(token)
                    self.report.error(argument_line, label,
                                      f"argument {token} is a file in the pinned tree; list it under Entrypoints too.")

    def fact(self, section: er.Section) -> None:
        label, ident = self.label(section), section.ident
        candidate = self.facts[ident]
        decision = self.decision(section, DECISIONS)
        if decision in (None, _PENDING):
            return
        self.result.counts[decision] += 1
        decision_line = _field_line(section, "Decision")
        reason = self.reason(section)
        if decision == "reject":
            if not reason:
                self.report.error(decision_line, label,
                                  'Decision is reject but "Reason:" is missing. Say why the claim is wrong or not needed.')
            for key in ("Wording", "Basis", "Anchors"):
                if self.has(section, key):
                    self.report.error(_field_line(section, key), label,
                                      f"a rejected fact takes no {key}; delete the line or change the decision.")
            if self.has(section, "Essential"):
                self.report.error(_field_line(section, "Essential"), label,
                                  "a rejected fact cannot be essential; delete the Essential line or change the decision.")
            self.result.rejected_facts.append({"id": ident, "candidateClaim": candidate["claim"], "reason": reason})
            self.position(ident, {"decision": "reject"})
            return
        wording = _value(section, "Wording")
        if decision == "qualify":
            if not wording:
                self.report.error(decision_line, label, 'Decision is qualify but there is no "Wording:" line. '
                                                        'Add "Wording: <your corrected claim>".')
            if not reason:
                self.report.error(decision_line, label,
                                  'Decision is qualify but "Reason:" is missing. Say what the proposed claim got wrong.')
        elif wording:
            self.report.error(_field_line(section, "Wording"), label,
                              'Wording is used only with "Decision: qualify". Change the decision or delete the line.')
        changed: dict[str, int] = {}
        basis = candidate["basis"]
        chosen = self.basis(section)
        if chosen is not None:
            if chosen != basis:
                changed["basis"] = _field_line(section, "Basis")
            basis = chosen
        essential = bool(candidate["essential"])
        flag = self.yes_no(section, "Essential")
        if flag is not None:
            if flag != essential:
                changed["essential"] = _field_line(section, "Essential")
            essential = flag
        anchors = [_candidate_anchor(anchor) for anchor in candidate["anchors"]]
        if self.has(section, "Anchors"):
            parsed = self.anchor_list(section)
            if parsed is not None:
                if set(parsed) != {_location(anchor) for anchor in candidate["anchors"]}:
                    changed["anchors"] = _field_line(section, "Anchors")
                anchors = _merge_anchors(ident, candidate["anchors"], parsed)
        if not anchors and basis != "unresolved":
            self.report.error(_field_line(section, "Anchors"), label,
                              "a fact needs at least one anchor unless Basis is unresolved.")
        if changed and decision == "accept" and not reason:
            names = [name.capitalize() for name in ("basis", "essential", "anchors") if name in changed]
            verb = "differs" if names in (["Basis"], ["Essential"]) else "differ"
            self.report.error(min(changed.values()), label,
                              f'{_join_names(names)} {verb} from the proposal; add "Reason:" saying why.')
        claim = wording if decision == "qualify" and wording else candidate["claim"]
        changes = sorted(set(changed) | ({"claim"} if claim != candidate["claim"] else set()))
        self.result.facts.append({"id": ident, "origin": "candidate", "decision": decision, "claim": claim,
                                  "candidateClaim": candidate["claim"], "basis": basis, "essential": essential,
                                  "changed": changes, "anchors": anchors, "reason": reason})
        if essential:
            self.result.essential_so_far.append(ident)
        self.position(ident, {"decision": decision, "basis": basis, "essential": essential})

    def _qualify_rules(self, section: er.Section, decision: str, what: str) -> None:
        label, decision_line = self.label(section), _field_line(section, "Decision")
        if decision == "qualify":
            if not self.has(section, "Wording"):
                self.report.error(decision_line, label, 'Decision is qualify but there is no "Wording:" line. '
                                                        'Add "Wording: <your corrected text>".')
            if not self.reason(section):
                self.report.error(decision_line, label,
                                  'Decision is qualify but "Reason:" is missing. Say what the proposed text got wrong.')
        elif decision == "accept" and self.has(section, "Wording"):
            self.report.error(_field_line(section, "Wording"), label,
                              'Wording is used only with "Decision: qualify". Change the decision or delete the line.')
        elif decision == "reject":
            if not self.reason(section):
                self.report.error(decision_line, label, f'Decision is reject but "Reason:" is missing. Say why {what}.')
            if self.has(section, "Wording"):
                self.report.error(_field_line(section, "Wording"), label,
                                  f"a rejected {section.kind.casefold()} takes no Wording; delete the line or change "
                                  "the decision.")

    def unknown(self, section: er.Section) -> None:
        label, ident = self.label(section), section.ident
        text = self.unknown_text[ident]
        decision = self.decision(section, DECISIONS)
        if decision in (None, _PENDING):
            return
        self._qualify_rules(section, decision, "this is not a real uncertainty or not needed")
        runs = section.field("Runs must state")
        reason = self.reason(section)
        if decision == "reject":
            if runs is not None and runs.value.strip():
                self.report.error(runs.line, label, 'a rejected unknown takes no "Runs must state"; delete the value.')
            self.result.rejected_unknowns.append({"id": ident, "candidateText": text, "reason": reason})
            self.position(ident, {"decision": "reject"})
            return
        must = self.runs_must_state(section)
        wording = _value(section, "Wording")
        effective = wording if decision == "qualify" and wording else text
        self.result.unknowns.append({"id": ident, "origin": "candidate", "decision": decision, "text": effective,
                                     "candidateText": text, "runsMustState": bool(must), "reason": reason})
        if must is not None:
            self.position(ident, {"decision": decision, "runsMustState": must})

    def runs_must_state(self, section: er.Section) -> bool | None:
        runs = section.field("Runs must state")
        value = runs.value.strip().casefold() if runs is not None else ""
        if not value:
            self.report.todo(runs.line if runs else _field_line(section, "Decision"), self.label(section),
                             '"Runs must state:" must be yes (every run must state this uncertainty) or no.')
            return None
        if value not in YES_NO:
            self.report.error(runs.line, self.label(section), f'"Runs must state: {runs.value.strip()}" must be yes or no.')
            return None
        return YES_NO[value]

    def nondefect(self, section: er.Section) -> None:
        ident = section.ident
        text = self.nondefect_text[ident]
        decision = self.decision(section, DECISIONS)
        if decision in (None, _PENDING):
            return
        self._qualify_rules(section, decision, "this is not intended behaviour or not needed")
        reason = self.reason(section)
        if decision == "reject":
            self.result.rejected_nondefects.append({"id": ident, "candidateText": text, "reason": reason})
        else:
            wording = _value(section, "Wording")
            self.result.nondefects.append({"id": ident, "decision": decision,
                                           "text": wording if decision == "qualify" and wording else text,
                                           "candidateText": text, "reason": reason})
        self.position(ident, {"decision": decision})

    def added_id(self, section: er.Section, message: str) -> None:
        if not re.fullmatch(added_patterns(self.task_id)[section.kind], section.ident or ""):
            self.report.error(section.line, self.label(section), message)

    def require(self, section: er.Section, keys: Sequence[str]) -> None:
        for key in keys:
            if not self.has(section, key):
                self.report.error(section.line, self.label(section), f'"{key}:" is missing.')

    def added_fact(self, section: er.Section) -> None:
        label, ident = self.label(section), section.ident
        self.added_id(section, f"added fact IDs look like {self.short}-h01, {self.short}-h02, ...")
        self.require(section, ("Wording", "Basis", "Essential", "Reason"))
        basis = self.basis(section)
        essential = self.yes_no(section, "Essential")
        anchors: list[dict] = []
        if self.has(section, "Anchors"):
            parsed = self.anchor_list(section) or []
            anchors = [_new_anchor(f"{ident}-a{index}", location) for index, location in enumerate(parsed, 1)]
        elif basis != "unresolved":
            self.report.error(section.line, label, '"Anchors:" is required unless Basis is unresolved.')
        self.result.added_facts += 1
        if essential:
            self.result.essential_so_far.append(ident)
        self.result.facts.append({"id": ident, "origin": "added", "decision": "added", "claim": _value(section, "Wording"),
                                  "candidateClaim": None, "basis": basis, "essential": bool(essential), "changed": [],
                                  "anchors": anchors, "reason": self.reason(section)})
        if basis is not None and essential is not None:
            self.position(ident, {"decision": "added", "basis": basis, "essential": essential})

    def added_unknown(self, section: er.Section) -> None:
        ident = section.ident
        self.added_id(section, f"added unknown IDs look like {self.short}-hu01, {self.short}-hu02, ...")
        self.require(section, ("Wording", "Reason"))
        must = self.yes_no(section, "Runs must state")
        if not self.has(section, "Runs must state"):
            self.report.error(section.line, self.label(section), '"Runs must state:" is missing.')
        self.result.unknowns.append({"id": ident, "origin": "added", "decision": "added", "text": _value(section, "Wording"),
                                     "candidateText": None, "runsMustState": bool(must), "reason": self.reason(section)})
        if must is not None:
            self.position(ident, {"decision": "added", "runsMustState": must})

    def defect(self, section: er.Section) -> None:
        label, ident = self.label(section), section.ident
        self.added_id(section, f"defect IDs look like {self.short}-d01, {self.short}-d02, ...")
        self.require(section, ("Wording", "Severity", "Anchors", "Counter-evidence", "Reason"))
        severity_field = section.field("Severity")
        severity = severity_field.value.strip().casefold() if severity_field is not None else ""
        if severity and severity not in SEVERITIES:
            self.report.error(severity_field.line, label,
                              f'"Severity: {severity_field.value.strip()}" must be high, medium or low.')
            severity = ""
        anchors: list[dict] = []
        if self.has(section, "Anchors"):
            parsed = self.anchor_list(section) or []
            anchors = [_new_anchor(f"{ident}-a{index}", location) for index, location in enumerate(parsed, 1)]
        if severity == "high" and self.primary and (self.second is None or ident not in self.second.positions):
            self.report.note(section.line, label,
                             "a second reviewer is recommended for high-severity defects (REVIEW_GUIDE).")
        self.result.defects.append({"id": ident, "text": _value(section, "Wording"), "severity": severity or None,
                                    "anchors": anchors, "counterEvidence": _value(section, "Counter-evidence"),
                                    "reason": self.reason(section)})
        if severity:
            self.position(ident, {"decision": "added", "severity": severity})

    def disagreements(self) -> None:
        section = self.record.section("Disagreements")
        second = self.second
        resolutions: dict[str, er.Field] = {}
        known_items = set(self.result.positions) | {"scenario"}
        differing: list[tuple[str, dict, dict]] = []
        if second is not None:
            for ident, mine in self.result.positions.items():
                theirs = second.positions.get(ident)
                if theirs is not None and theirs != mine:
                    differing.append((ident, mine, theirs))
        disagreeing = {ident for ident, _mine, _theirs in differing}
        if section is not None:
            for line in section.lines:
                key = line.key.strip()
                match = next((ident for ident in disagreeing if ident.casefold() == key.casefold()), None)
                if match is None:
                    if second is None:
                        message = (f'"{key}": there is no second review ({self.task_id}.second.md) to disagree with; '
                                   "delete this line.")
                    elif key.casefold() in {item.casefold() for item in known_items}:
                        message = f'"{key}" does not disagree with the second review; delete this line.'
                    else:
                        message = f'"{key}" is not an item that disagrees with the second review; delete this line.'
                    self.report.error(line.line, "Disagreements", message)
                    continue
                resolutions[match] = line
        where = section.line if section is not None else 1
        name = f" ({second.reviewer})" if second is not None and second.reviewer else ""
        for ident, mine, theirs in differing:
            resolution = resolutions.get(ident)
            if resolution is None or not resolution.value.strip():
                self.report.todo(resolution.line if resolution else where, "Disagreements",
                                 f"{ident}: the second reviewer{name} chose {_describe(theirs, mine)}; you chose "
                                 f'{_describe(mine, theirs)}. Add "{ident}: <how it was resolved>".')
                continue
            self.result.disputes.append({"item": ident, "primary": mine, "second": theirs,
                                         "resolution": resolution.value.strip()})


_POSITION_LABELS = (("basis", "basis"), ("essential", "essential"), ("runsMustState", "runs must state"),
                    ("severity", "severity"))


def _describe(mine: dict, other: dict) -> str:
    extras = []
    for key, label in _POSITION_LABELS:
        if key in mine and key in other and mine[key] != other[key]:
            value = mine[key]
            extras.append(f"{label}: {_yes_no(value) if isinstance(value, bool) else value}")
    if mine.get("decision") == "added":
        return ", ".join(extras) if extras else "added"
    return mine["decision"] + (f" ({', '.join(extras)})" if extras else "")


def _argument_tokens(argument: str) -> list[str]:
    tokens: list[str] = []
    for token in argument.split():
        for candidate in (token, token.split("=", 1)[1] if "=" in token else None):
            if not candidate:
                continue
            if candidate.startswith("./"):
                candidate = candidate[2:]
            if candidate and candidate not in tokens:
                tokens.append(candidate)
    return tokens


def _location(anchor: dict) -> tuple[str, int | None, int, int]:
    return anchor["file"], anchor.get("cell"), anchor["line"], anchor["endLine"]


def _new_anchor(ident: str, location: tuple[str, int | None, int, int]) -> dict:
    path, cell, line, end = location
    anchor = {"id": ident, "file": path, "line": line, "endLine": end}
    if cell is not None:
        anchor["cell"] = cell
    return anchor


def _candidate_anchor(anchor: dict) -> dict:
    return _new_anchor(anchor["id"], _location(anchor))


def _merge_anchors(fact_id: str, candidates: list[dict], parsed: list[tuple]) -> list[dict]:
    """The listed anchors: a candidate anchor keeps its ID when its locator is listed; new
    locators get ``<fact id>-h1``, ``-h2``, ... in the order listed."""
    by_location = {_location(anchor): anchor for anchor in candidates}
    merged, counter = [], 0
    for location in parsed:
        if location in by_location:
            merged.append(_candidate_anchor(by_location[location]))
        else:
            counter += 1
            merged.append(_new_anchor(f"{fact_id}-h{counter}", location))
    return merged


def check_reference(world: World, raw: bytes, display: str, *, second: RefCheck | None = None,
                    expected_name: str | None = None) -> RefCheck:
    """Check one reference-decisions or second-review file. ``second`` is the checked second
    review of the same task (primary files only)."""
    report = Report(display)
    record, problems = er.parse_record(raw, display)
    report.problems.extend(problems)
    role = "second" if record is not None and record.kind == "Second review" else "primary"
    result = RefCheck(record.ident if record else None, role, display, report, record)
    if record is None:
        return result
    task = world.heldout_task(record.ident)
    if task is None:
        report.error(record.header.line, "header", f"{record.ident} is not a held-out task in {TASKS_REL}.")
        result.task_id = None
        return result
    if expected_name is not None and expected_name != record.ident:
        report.error(record.header.line, "header", f"the title names {record.ident} but the file is for "
                                                   f"{expected_name}; restore the title the tool wrote.")
    result.second = second
    _RefChecker(world, record, report, result, task, second).run()
    return result


def reference_summary(world: World, result: RefCheck) -> list[str]:
    lines = [f"{result.name}: {result.errors} error(s), {result.todos} to do; {state_text(result.errors, result.todos)}."]
    if result.record is None or result.task_id is None:
        return lines
    counts = result.counts
    task = world.heldout_task(result.task_id) or {}
    if result.role == "second":
        lines.append(f"  items decided: {result.decided}; facts: {counts['accept']} accept, {counts['qualify']} "
                     f"qualify, {counts['reject']} reject")
    elif result.errors or result.todos:
        essential = result.essential_so_far
        lines.append(f"  facts decided: {counts['accept']} accept, {counts['qualify']} qualify, {counts['reject']} "
                     f"reject; essential so far ({len(essential)}): {' '.join(essential) or '-'}")
    else:
        essential = [fact["id"] for fact in result.facts if fact["essential"]]
        must = [item["id"] for item in result.unknowns if item["runsMustState"]]
        lines.append(f"  facts: {counts['accept']} accept, {counts['qualify']} qualify, {counts['reject']} reject; "
                     f"added {result.added_facts}; essential ({len(essential)}): {' '.join(essential) or '-'}")
        lines.append(f"  unknowns: {len(result.unknowns)} kept (runs must state: {' '.join(must) or '-'}); "
                     f"non-defects: {len(result.nondefects)} kept; defects: {len(result.defects)}")
    if not result.corpus_checked:
        lines.append("  anchors not checked: corpus absent (freeze requires it)")
    elif result.role == "primary" and not result.errors and not result.todos:
        lines.append(f"  anchors checked against {task.get('repository')}@{str(task.get('commit'))[:12]} "
                     f"({world.corpus_display(task)})")
    return lines


# --------------------------------------------------------------------------------------------
# Run policy


@dataclass
class PolicyCheck:
    display: str
    report: Report
    record: er.Record | None = None
    reviewer: str = ""
    date: str = ""
    transcribed_by: str = ""
    review: str | None = None
    values: dict = field(default_factory=dict)
    skill_template: str | None = None
    baseline_template: str | None = None

    @property
    def errors(self) -> int:
        return self.report.errors

    @property
    def todos(self) -> int:
        return self.report.todos

    @property
    def ready(self) -> bool:
        return self.record is not None and not self.errors and not self.todos and self.review == "complete"


def check_policy(world: World, raw: bytes, display: str) -> PolicyCheck:
    report = Report(display)
    record, problems = er.parse_record(raw, display)
    report.problems.extend(problems)
    result = PolicyCheck(display, report, record)
    if record is None:
        return result
    _reviewer_header(report, record)
    result.reviewer = _value(record.header, "Reviewer")
    result.date = _value(record.header, "Date")
    result.transcribed_by = _value(record.header, "Transcribed by")
    hosts = world.hosts
    command = f"{TEMPLATE_COMMAND} --show {POLICY_TARGET}"
    expected = [("Host", host) for host in hosts] + [(kind, None) for kind in (
        "Environment", "Budget", "Scoring", "Conditions", "Targets", "Skill prompt", "No-skill prompt", "Privacy", "Task")]
    _missing_sections(report, record, expected, command)
    values: dict = {"hosts": {}}

    def text(section: er.Section, key: str, message: str) -> str | None:
        found = section.field(key)
        value = found.value.strip() if found is not None else ""
        if not value:
            report.todo(found.line if found else section.line, section.label, f"{key} is empty. {message}")
            return None
        machine = _machine_path(value)
        if machine:
            report.error(found.line, section.label, f"{key} contains an absolute machine path ({machine}); describe it "
                                                    "without one.")
            return None
        return value

    def choice(section: er.Section, key: str, allowed: Sequence[str]) -> str | None:
        found = section.field(key)
        value = found.value.strip().casefold() if found is not None else ""
        if not value:
            report.todo(found.line if found else section.line, section.label,
                        f"{key} is empty. Write one of: {', '.join(allowed)}.")
            return None
        if value not in allowed:
            report.error(found.line, section.label, f'"{key}: {found.value.strip()}" must be one of: {", ".join(allowed)}.')
            return None
        return value

    def number(section: er.Section, key: str, low: int, high: int) -> int | None:
        found = section.field(key)
        value = found.value.strip() if found is not None else ""
        if not value:
            report.todo(found.line if found else section.line, section.label,
                        f"{key} is empty. Write a whole number from {low} to {high}.")
            return None
        if not INTEGER_RE.fullmatch(value) or not low <= int(value) <= high:
            report.error(found.line, section.label, f'"{key}: {value}" must be a whole number from {low} to {high}.')
            return None
        return int(value)

    def accepted(section: er.Section, message: str) -> bool:
        found = section.field("Decision")
        value = found.value.strip().casefold() if found is not None else ""
        if found is None:
            report.error(section.line, section.label, 'the "Decision:" line is missing.')
            return False
        if value in ("", _PENDING):
            report.todo(found.line, section.label, "Decision is still pending.")
            return False
        if value != "accept":
            report.error(found.line, section.label, f'"Decision: {found.value.strip()}" is not a decision. {message}')
            return False
        return True

    for section in record.sections:
        if section.kind == "Host":
            if section.ident not in hosts:
                report.error(section.line, section.label,
                             f'"{section.ident}" is not a host in {TASKS_REL} ({", ".join(hosts)}).')
                continue
            values["hosts"][section.ident] = {
                "model": text(section, "Model", f"Write the exact model setting every {section.ident} run must use."),
                "reasoning": text(section, "Reasoning", f"Write the exact reasoning setting every {section.ident} run "
                                                        'must use (or "not exposed").'),
                "invocation": text(section, "Invocation", f"Write how every {section.ident} run invokes the skill."),
            }
        elif section.kind == "Environment":
            values["helperPython"] = text(section, "Helper Python", "Say how each host's terminal resolves python3 to "
                                                                    "Python 3.10 or newer (no machine path).")
        elif section.kind == "Budget":
            values["activeMinutes"] = number(section, "Active minutes", 1, 240)
            values["repairRounds"] = number(section, "Repair rounds", 0, 5)
            values["infrastructureRetries"] = number(section, "Infrastructure retries", 0, 1)
        elif section.kind == "Scoring":
            values["qualifiedClaims"] = choice(section, "Qualified claims", QUALIFIED_CLAIMS)
            per_host = choice(section, "Per-host targets", tuple(YES_NO))
            values["perHostTargets"] = None if per_host is None else YES_NO[per_host]
        elif section.kind == "Conditions":
            count = str(baseline_session_count(world))
            sessions = choice(section, "Baseline sessions", (count, "0"))
            values["baselineSessions"] = None if sessions is None else int(sessions)
            values["developmentAdjudication"] = choice(section, "Development adjudication before Stage 1",
                                                       ADJUDICATION_GATE)
        elif section.kind == "Targets":
            values["targets"] = accepted(section, f"Write accept (to change a target, edit {TASKS_REL} pilotTargets "
                                                  "before the freeze).")
        elif section.kind in ("Skill prompt", "No-skill prompt"):
            skill = section.kind == "Skill prompt"
            ok = accepted(section, "Write accept once the prompt text is final.")
            if section.fence is None:
                report.error(section.line, section.label,
                             "the prompt text must be a fenced block (```text ... ```); restore it from the template.")
                continue
            _prompt_rules(report, section, section.fence, skill)
            if skill:
                result.skill_template = section.fence
                values["skillPrompt"] = ok
            else:
                result.baseline_template = section.fence
                values["baselinePrompt"] = ok
        elif section.kind == "Privacy":
            values["publication"] = text(section, "Publication", "Say what, if anything, may be published besides "
                                                                 "counts, statuses and hashes.")
    result.values = values
    result.review = _task_section(report, record, closing="every decision above is final")
    return result


def _prompt_rules(report: Report, section: er.Section, template: str, skill: bool) -> None:
    line = section.fence_line or section.line
    found = PROMPT_PLACEHOLDER_RE.findall(template)
    unknown = sorted({name for name in found if name not in PLACEHOLDERS})
    if unknown:
        report.error(line, section.label, f"the prompt uses unknown placeholder(s) {', '.join('{' + n + '}' for n in unknown)}; "
                                          "the placeholders are {task_prompt}, {scenario} and {artifact_path}.")
    required = PLACEHOLDERS if skill else ("task_prompt", "scenario")
    for name in required:
        if name not in found:
            report.error(line, section.label, f"the {'skill' if skill else 'no-skill'} prompt must contain {{{name}}}.")
    if not skill:
        if "artifact_path" in found:
            report.error(line, section.label, "the no-skill prompt must not contain {artifact_path}; a baseline "
                                              "publishes nothing.")
        for match in sorted({m.group(0) for m in NO_SKILL_FORBIDDEN_RE.finditer(template)}, key=str.casefold):
            report.error(line, section.label, f'the no-skill prompt must not mention "{match}" '
                                              "(CANDIDATE_PROTOCOL.md:43-44).")
    machine = _machine_path(template)
    if machine:
        report.error(line, section.label, f"the prompt contains an absolute machine path ({machine}); prompts must "
                                          "not name machine paths.")


def policy_summary(result: PolicyCheck) -> list[str]:
    lines = [f"{POLICY_TARGET}: {result.errors} error(s), {result.todos} to do; {state_text(result.errors, result.todos)}."]
    values = result.values
    if result.record is not None:
        hosts = values.get("hosts", {})
        filled = sum(1 for entry in hosts.values() if all(entry.values()))
        prompts = sum(1 for key in ("skillPrompt", "baselinePrompt") if values.get(key))
        lines.append(f"  hosts filled: {filled} of {len(hosts)}; prompts accepted: {prompts} of 2; targets: "
                     f"{'accepted' if values.get('targets') else 'pending'}")
    return lines


def render_prompt(template: str, task: dict, scenario: dict) -> str:
    block = "\n".join([f"Description: {one_line(scenario['description'])}",
                       f"Entrypoints: {', '.join(scenario['entrypoints'])}",
                       f"Arguments: {' '.join(scenario['arguments']) or 'none'}"])
    values = {"task_prompt": task["prompt"], "scenario": block, "artifact_path": ARTIFACT_PATH}
    text = PROMPT_PLACEHOLDER_RE.sub(lambda match: values.get(match.group(1), match.group(0)), template)
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(lines).rstrip("\n") + "\n"


def policy_record(world: World, result: PolicyCheck, source_rel: str, raw: bytes, campaign: str) -> dict:
    values = result.values
    targets = world.manifest.get("pilotTargets") or {}
    return {
        "format": "mlview-run-policy/1", "campaign": campaign,
        "source": {"path": source_rel, "sha256": er.sha256_bytes(raw), "reviewer": result.reviewer,
                   "date": result.date, "transcribedBy": result.transcribed_by or None},
        "hosts": {host: dict(values["hosts"][host]) for host in world.hosts},
        "environment": {"helperPython": values["helperPython"]},
        "budget": {"activeMinutes": values["activeMinutes"], "repairRounds": values["repairRounds"],
                   "infrastructureRetries": values["infrastructureRetries"]},
        "scoring": {"qualifiedClaims": values["qualifiedClaims"], "perHostTargets": values["perHostTargets"]},
        "conditions": {"baselineSessions": values["baselineSessions"],
                       "developmentAdjudicationBeforeStage1": values["developmentAdjudication"]},
        "targets": {key: targets.get(key) for key in er.PILOT_TARGET_KEYS},
        "privacy": {"publication": values["publication"]},
        "prompts": {"artifactPath": ARTIFACT_PATH,
                    "skillTemplateSha256": er.sha256_bytes(result.skill_template.encode("utf-8")),
                    "baselineTemplateSha256": er.sha256_bytes(result.baseline_template.encode("utf-8"))},
    }


# --------------------------------------------------------------------------------------------
# Development adjudication


@dataclass
class AdjudicationCheck:
    display: str
    report: Report
    record: er.Record | None = None
    review: str | None = None
    sections: list[dict] = field(default_factory=list)
    baselines: dict[str, str] = field(default_factory=dict)
    baselines_decided: int = 0
    confusion: dict[str, dict[tuple[str, str], int]] = field(default_factory=lambda: {"claims": {}, "usability": {}})

    @property
    def errors(self) -> int:
        return self.report.errors

    @property
    def todos(self) -> int:
        return self.report.todos

    @property
    def complete(self) -> bool:
        return self.record is not None and not self.errors and not self.todos and self.review == "complete"


def check_adjudication(world: World, raw: bytes, display: str) -> AdjudicationCheck:
    report = Report(display)
    record, problems = er.parse_record(raw, display)
    report.problems.extend(problems)
    result = AdjudicationCheck(display, report, record)
    if record is None:
        return result
    workflow_eval = _workflow_eval()
    _reviewer_header(report, record)
    command = f"{TEMPLATE_COMMAND} --show {ADJUDICATION_TARGET}"
    ledgers = adjudication_ledgers(world)
    expected = [(f"{task} / {host}".casefold(), None) for task, host, _rel in ledgers] + [("Baselines", None),
                                                                                          ("Task", None)]
    _missing_sections(report, record, expected, command)
    by_kind = {f"{task} / {host}".casefold(): (task, host, rel) for task, host, rel in ledgers}
    usability_set = set(getattr(workflow_eval, "USABILITY_QUESTIONS", USABILITY_ORDER))
    if usability_set != set(USABILITY_ORDER):
        report.error(record.header.line, "header", "tools/workflow_eval.py USABILITY_QUESTIONS changed; update "
                                                   "tools/workflow_decisions.py.")
    for section in record.sections:
        if section.kind in ("Task",):
            continue
        label = section.label
        if section.kind == "Baselines":
            _adjudicate_baselines(world, workflow_eval, report, section, result)
            continue
        if section.kind not in by_kind:
            report.error(section.line, label, f'unknown section "## {label}". Sections are the 12 "<task> / <host>" '
                                              "pairs, Baselines and Task.")
            continue
        task, host, rel = by_kind[section.kind]
        try:
            ledger, ledger_raw = _development_json(world, rel)
        except (OSError, ValueError) as exc:
            report.error(section.line, label, f"cannot read {rel}: {exc}")
            continue
        ledger_line = _ledger_line(report, section, rel, ledger_raw)
        try:
            workflow_eval.validate_development_review(ledger, world.root)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            report.error(ledger_line, label, f"{rel} does not validate: {exc}")
        provisional = {claim["id"]: ("claims", claim["verdict"]) for claim in ledger.get("claims") or []}
        for question in USABILITY_ORDER:
            status = (ledger.get("usability") or {}).get(question, {}).get("status")
            provisional[f"usability.{question}"] = ("usability", status)
        stats = {"label": label, "claims": 0, "claimsTotal": sum(1 for v in provisional.values() if v[0] == "claims"),
                 "usability": 0, "agree": 0}
        seen: set[str] = set()
        folded = {key.casefold(): key for key in provisional}
        for line in section.lines:
            if line.key.casefold() == "ledger":
                continue
            key = folded.get(line.key.casefold())
            if key is None:
                report.error(line.line, label, f'"{line.key}" is not a claim of {rel} or a usability question.')
                continue
            seen.add(key)
            group, prior = provisional[key]
            vocab = set(workflow_eval.REVIEW_VERDICTS) if group == "claims" else set(USABILITY_VERDICTS)
            verdict = _adjudicated(report, line, label, key, vocab, prior)
            if verdict is None:
                continue
            stats[group] += 1
            stats["agree"] += int(verdict == prior)
            cell = (prior, verdict)
            result.confusion[group][cell] = result.confusion[group].get(cell, 0) + 1
        for key in provisional:
            if key not in seen:
                report.error(section.line, label, f"{key} is missing; restore its line from the template ({command}).")
        result.sections.append(stats)
    result.review = _task_section(report, record, closing="every verdict above is final")
    return result


def _ledger_line(report: Report, section: er.Section, rel: str, raw: bytes) -> int:
    found = next((line for line in section.lines if line.key.casefold() == "ledger"), None)
    if found is None or " ".join(found.value.split()) != f"{rel} {er.sha256_bytes(raw)}":
        report.error(found.line if found else section.line, section.label,
                     f"the Ledger line does not match {rel} (ledgers are immutable); restore the line the tool wrote.")
    return found.line if found else section.line


def _adjudicated(report: Report, line: er.Field, label: str, key: str, vocab: set[str], prior: str | None,
                 *, reason_always: bool = False) -> str | None:
    value = line.value.strip()
    if value.casefold() in ("", _PENDING):
        report.todo(line.line, label, f"{key} is still pending.")
        return None
    try:
        verdict, pointers, reason = er.parse_verdict(value, vocab)
    except ValueError as exc:
        report.error(line.line, label, f"{key}: {exc}")
        return None
    if pointers:
        report.error(line.line, label, f'{key}: write the verdict and an optional " — <reason>"; '
                                       f'"{" ".join(pointers)}" is not expected.')
        return None
    if reason_always and verdict != prior and not reason:
        report.error(line.line, label, f'"{key}: {verdict}" needs a reason; add " — <reason>".')
        return None
    if not reason_always and verdict != prior and not reason:
        report.error(line.line, label,
                     f'"{key}: {verdict}" differs from the provisional "{prior}"; add " — <reason>".')
        return None
    return verdict


def _adjudicate_baselines(world: World, workflow_eval, report: Report, section: er.Section,
                          result: AdjudicationCheck) -> None:
    rel = "native-reviews/baselines.json"
    try:
        value, raw = _development_json(world, rel)
    except (OSError, ValueError) as exc:
        report.error(section.line, section.label, f"cannot read {rel}: {exc}")
        return
    ledger_line = _ledger_line(report, section, rel, raw)
    try:
        workflow_eval.validate_baselines(value, world.manifest, world.root)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        report.error(ledger_line, section.label, f"{rel} does not validate: {exc}")
    hosts = {host.casefold(): host for host in world.hosts}
    seen: set[str] = set()
    for line in section.lines:
        if line.key.casefold() == "ledger":
            continue
        host = hosts.get(line.key.casefold())
        if host is None:
            report.error(line.line, section.label, f'"{line.key}" is not a host with a baseline note '
                                                   f'({", ".join(world.hosts)}).')
            continue
        seen.add(host)
        verdict = _adjudicated(report, line, section.label, host, set(BASELINE_VERDICTS), "confirmed",
                               reason_always=True)
        if verdict is not None:
            result.baselines[host] = verdict
            result.baselines_decided += 1
    for host in world.hosts:
        if host not in seen:
            report.error(section.line, section.label, f"{host} is missing; restore its line from the template "
                                                      f"({TEMPLATE_COMMAND} --show {ADJUDICATION_TARGET}).")


def adjudication_summary(result: AdjudicationCheck) -> list[str]:
    lines = [f"{ADJUDICATION_TARGET}: {result.errors} error(s), {result.todos} to do; "
             f"{state_text(result.errors, result.todos, 'complete')}."]
    for stats in result.sections:
        if stats["claims"] or stats["usability"]:
            verb = "agrees" if stats["agree"] == 1 else "agree"
            lines.append(f"  {stats['label']}: {stats['claims']} of {stats['claimsTotal']} claims, {stats['usability']} "
                         f"of {len(USABILITY_ORDER)} usability decided; {stats['agree']} {verb} with the provisional label.")
    if result.baselines_decided:
        lines.append(f"  baselines: {result.baselines_decided} decided")
    if result.complete:
        lines.append("  Development evidence; not a held-out pilot result.")
        workflow_eval = _workflow_eval()
        claim_order = [v for v in ("supported", "qualified", "unsupported", "omitted") if v in workflow_eval.REVIEW_VERDICTS]
        for group, order in (("claims", claim_order), ("usability", list(USABILITY_VERDICTS))):
            lines.append(f"  {group} (rows: provisional, columns: human)")
            width = max(len(name) for name in order) + 2
            lines.append("    " + " " * width + "".join(f"{name:>{width}}" for name in order))
            for prior in order:
                row = "".join(f"{result.confusion[group].get((prior, human), 0):>{width}}" for human in order)
                lines.append(f"    {prior:<{width}}{row}")
        lines.append("  baselines: " + "; ".join(f"{host} {verdict}" for host, verdict in result.baselines.items()))
    return lines


# --------------------------------------------------------------------------------------------
# The check command


def _sibling(name: str, *, required: bool = False):
    path = TOOLS / f"{name}.py"
    loaded = sys.modules.get(name)
    if loaded is not None and Path(getattr(loaded, "__file__", "") or "").resolve() == path.resolve():
        return loaded
    if not path.is_file():
        if required:
            raise UsageError(f"tools/{name}.py is missing")
        return None
    return importlib.import_module(name)


def decision_files(world: World) -> list[Path]:
    if not world.decisions_dir.is_dir():
        return []
    return sorted(path for path in world.decisions_dir.glob("*.md") if path.name != "README.md" and path.is_file())


def resolve_target(world: World, target: str) -> Path:
    if world.heldout_task(target) is not None or target in (POLICY_TARGET, ADJUDICATION_TARGET):
        path = world.decisions_dir / f"{target}.md"
        if not path.is_file():
            hint = f"{TEMPLATE_COMMAND} {target}"
            raise UsageError(f"{world.display(path)} does not exist; create it with {hint}")
        return path
    path = Path(target)
    if path.is_file():
        return path
    raise UsageError(f"{target} is not a held-out task ID, {POLICY_TARGET}, {ADJUDICATION_TARGET} or an existing file")


def _expected_name(world: World, path: Path, second: bool) -> str | None:
    try:
        inside = path.resolve().parent == world.decisions_dir.resolve()
    except OSError:
        inside = False
    if not inside:
        return None
    suffix = ".second.md" if second else ".md"
    return path.name[:-len(suffix)] if path.name.endswith(suffix) else None


def title_kind(raw: bytes) -> str | None:
    record, _problems = er.parse_record(raw, "-")
    return record.kind if record is not None else None


@dataclass
class FileCheck:
    display: str
    problems: list[er.Problem]
    summary: list[str]
    errors: int
    todos: int
    result: object = None


def check_path(world: World, path: Path, *, with_second: bool = True) -> list[FileCheck]:
    """Check one file (a primary file also checks its second review, when present)."""
    path = Path(path)
    raw = path.read_bytes()
    display = world.display(path)
    kind = title_kind(raw)
    if kind == "Reference decisions":
        second_check = None
        checks: list[FileCheck] = []
        second_path = path.with_name(path.name[:-3] + ".second.md") if path.name.endswith(".md") else None
        usable = None
        if with_second and second_path is not None and second_path.is_file():
            second_raw = second_path.read_bytes()
            second_check = check_reference(world, second_raw, world.display(second_path),
                                           expected_name=_expected_name(world, second_path, True))
            primary_record, _problems = er.parse_record(raw, display)
            ident = primary_record.ident if primary_record is not None else None
            if second_check.record is not None and (second_check.role != "second" or second_check.task_id != ident):
                second_check.report.error(second_check.record.header.line, "header",
                                          f'a second review must start with "# Second review: {ident}".')
            elif second_check.record is not None:
                usable = second_check
        result = check_reference(world, raw, display, second=usable, expected_name=_expected_name(world, path, False))
        checks.append(FileCheck(display, result.report.ordered(), reference_summary(world, result), result.errors,
                                result.todos, result))
        if second_check is not None:
            checks.append(FileCheck(second_check.display, second_check.report.ordered(),
                                    reference_summary(world, second_check), second_check.errors, second_check.todos,
                                    second_check))
        return checks
    if kind == "Second review":
        result = check_reference(world, raw, display, expected_name=_expected_name(world, path, True))
        return [FileCheck(display, result.report.ordered(), reference_summary(world, result), result.errors,
                          result.todos, result)]
    if kind == "Pilot run policy":
        result = check_policy(world, raw, display)
        return [FileCheck(display, result.report.ordered(), policy_summary(result), result.errors, result.todos, result)]
    if kind == "Development adjudication":
        result = check_adjudication(world, raw, display)
        return [FileCheck(display, result.report.ordered(), adjudication_summary(result), result.errors, result.todos,
                          result)]
    if kind in ("Session", "Run review"):
        pilot = _sibling("workflow_pilot")
        if pilot is None or not callable(getattr(pilot, "check_file", None)):
            problem = er.Problem(display, 1, er.ERROR, "header", f"{kind} files are checked by tools/workflow_pilot.py, "
                                                                 "which is not available in this build.")
            return [FileCheck(display, [problem], [f"{path.name}: 1 error(s), 0 to do; not ready (fix the errors)."], 1, 0)]
        problems = sorted(pilot.check_file(path), key=lambda p: (p.line, LEVEL_ORDER.get(p.level, 9)))
        errors = sum(1 for p in problems if p.level == er.ERROR)
        todos = sum(1 for p in problems if p.level == er.TODO)
        return [FileCheck(display, problems, [f"{path.name}: {errors} error(s), {todos} to do; "
                                              f"{state_text(errors, todos, 'complete')}."], errors, todos)]
    record, problems = er.parse_record(raw, display)
    if record is not None:  # a known title without a checker here (for example an invalidation record)
        problems = problems + [er.Problem(display, record.header.line, er.ERROR, "header",
                                          f'"# {record.kind}" files are not checked by this command.')]
    errors = sum(1 for p in problems if p.level == er.ERROR)
    return [FileCheck(display, problems, [f"{path.name}: {errors} error(s), 0 to do; not ready (fix the errors)."],
                      errors, 0)]


def show_prompts(world: World, policy: PolicyCheck) -> tuple[list[str], int]:
    """All 16 renderings, with each task's decided scenario or its proposal, and leak findings."""
    lines: list[str] = []
    findings = 0
    leak_texts = _leak_texts(world, {})
    for task in world.heldout:
        scenario, status = _effective_scenario(world, task["id"])
        for folder, template in (("skill", policy.skill_template), ("baseline", policy.baseline_template)):
            rel = f"prompts/{folder}/{task['id']}.txt"
            if template is None:
                lines.append(f"===== {rel}: no template (restore the fenced block) =====")
                continue
            text = render_prompt(template, task, scenario)
            lines.append(f"===== {rel} (scenario: {status}) =====")
            lines.extend(text.rstrip("\n").split("\n"))
            for problem in _prompt_findings(rel, text, leak_texts):
                findings += 1
                lines.append(f"LEAK  {problem}")
    lines.append(f"{2 * len(world.heldout)} prompts rendered; {findings} leak finding(s).")
    return lines, findings


def _effective_scenario(world: World, task_id: str) -> tuple[dict, str]:
    ledger, _raw = world.ledger(task_id)
    proposal = {"description": ledger["scenario"]["description"], "entrypoints": list(ledger["scenario"]["entrypoints"]),
                "arguments": list(ledger["scenario"]["arguments"])}
    path = world.decisions_dir / f"{task_id}.md"
    if not path.is_file():
        return proposal, "proposal; the decisions file does not exist"
    result = check_reference(world, path.read_bytes(), world.display(path))
    if result.scenario is None:
        return proposal, "proposal; the scenario decision is still pending"
    if any(problem.level == er.ERROR and problem.section == "Scenario" for problem in result.report.problems):
        return proposal, "proposal; the scenario decision has errors"
    return result.scenario, "accepted" if result.scenario["decision"] == "accept" else "replaced"


def _normalise(text: str) -> str:
    return " ".join(text.split()).casefold()


def _leak_texts(world: World, frozen: dict[str, dict]) -> list[tuple[str, str]]:
    """(label, normalised text) of every candidate and frozen reference text of 30+ characters."""
    texts: list[tuple[str, str]] = []
    for task in world.heldout:
        ledger, _raw = world.ledger(task["id"])
        for fact in ledger.get("facts") or []:
            texts.append((fact["id"], fact["claim"]))
        texts.extend(zip(unknown_ids(task["id"], ledger), ledger.get("unknowns") or []))
        texts.extend(zip(nondefect_ids(task["id"], ledger), ledger.get("nonDefects") or []))
    for reference in frozen.values():
        texts.extend((item["id"], item["claim"]) for item in reference["facts"])
        texts.extend((item["id"], item["text"]) for item in reference["knownUnresolved"])
        texts.extend((item["id"], item["text"]) for item in reference["nonDefects"])
        texts.extend((item["id"], item["text"]) for item in reference["defects"])
    out, seen = [], set()
    for label, text in texts:
        normal = _normalise(text or "")
        if len(normal) >= LEAK_MINIMUM and (label, normal) not in seen:
            seen.add((label, normal))
            out.append((label, normal))
    return out


def _prompt_findings(rel: str, text: str, leak_texts: list[tuple[str, str]]) -> list[str]:
    problems = []
    normal = _normalise(text)
    for label, reference in leak_texts:
        if reference in normal:
            problems.append(f"{rel} contains the reference text of {label} (reference leakage); change the scenario "
                            "or the prompt template.")
    machine = _machine_path(text)
    if machine:
        problems.append(f"{rel} contains an absolute machine path ({machine}).")
    return problems


def command_check(world: World, targets: Sequence[str], *, show: bool, out) -> int:
    if targets:
        paths = [resolve_target(world, target) for target in targets]
        with_second = True
    else:
        paths = decision_files(world)
        if not paths:
            raise UsageError(f"{world.display(world.decisions_dir)} has no decision files; create them with "
                             f"{TEMPLATE_COMMAND} --init-all")
        primaries = {path.name[:-3] for path in paths if not path.name.endswith(".second.md")}
        paths = [path for path in paths if not (path.name.endswith(".second.md")
                                                and path.name[:-len(".second.md")] in primaries)]
        with_second = True
    errors = 0
    first = True
    for path in paths:
        for check in check_path(world, path, with_second=with_second):
            if not first:
                print("", file=out)
            first = False
            for problem in check.problems:
                print(str(problem), file=out)
            for line in check.summary:
                print(line, file=out)
            errors += check.errors
            if show and isinstance(check.result, PolicyCheck):
                rendered, _findings = show_prompts(world, check.result)
                print("", file=out)
                for line in rendered:
                    print(line, file=out)
    if show and not any(title_kind(Path(p).read_bytes()) == "Pilot run policy" for p in paths):
        print("--show-prompts applies to the run policy; check run-policy --show-prompts", file=out)
    return 1 if errors else 0


# --------------------------------------------------------------------------------------------
# Context sheet


def context_sheet(world: World, task_id: str) -> tuple[str, int, int, list[str]]:
    """(markdown, facts, anchors, mismatches) of the local review-context sheet of one task."""
    task = world.heldout_task(task_id)
    if task is None:
        raise UsageError(f"{task_id} is not a held-out task in {TASKS_REL}")
    if world.repo_dir(task) is None:
        raise UsageError(f"the corpus checkout of {task.get('repository')} is absent; set MLVIEW_PUBLIC_CORPUS_DIR or "
                         "run python tools/fetch_workflow_repos.py")
    ledger, _raw = world.ledger(task_id)
    repo = world.repo_entry(task) or {}
    lines = [f"# Review context: {task_id}", "",
             f"> Local review aid written by python tools/workflow_eval.py context {task_id}. It is derived from the "
             "candidate ledger and the pinned source, gitignored, and may be rewritten; never commit it.",
             f"> Source: {task.get('repository')} ({task.get('url')}) at {task.get('commit')}; license: "
             f"{repo.get('license', 'see THIRD_PARTY_NOTICES.md')}.",
             "> The excerpts below are third-party source shown for review only (THIRD_PARTY_NOTICES.md). The sheet "
             "shows source; it does not judge any claim.", "",
             "## Scenario (proposed)",
             f"Description: {one_line(ledger['scenario']['description'])}",
             f"Entrypoints: {'; '.join(ledger['scenario']['entrypoints'])}",
             f"Arguments: {'; '.join(ledger['scenario']['arguments']) or 'none'}", ""]
    mismatches: list[str] = []
    anchors = 0
    for fact in ledger["facts"]:
        lines += [f"## Fact {fact['id']}", f"Claim: {one_line(fact['claim'])}",
                  f"Basis: {fact['basis']}. Essential: {_yes_no(fact['essential'])}.", ""]
        for anchor in fact["anchors"]:
            anchors += 1
            locator = _locator(anchor)
            try:
                data = world.pinned(task, anchor["file"])
                source = er.source_lines(data, anchor.get("cell"), world.helper)
            except ValueError as exc:
                mismatches.append(f"{anchor['id']} ({locator}): {exc}")
                lines += [f"### Anchor {anchor['id']}: {locator} (CANNOT READ: {exc})", ""]
                continue
            verified = er.quote_matches(anchor.get("quote"), source, anchor["line"], anchor["endLine"], world.helper)
            if not verified:
                mismatches.append(f"{anchor['id']} ({locator}): the candidate quote differs from the pinned bytes")
            status = "quote verified against the pinned bytes" if verified else "QUOTE MISMATCH against the pinned bytes"
            lines += [f"### Anchor {anchor['id']}: {locator} ({status})", *_numbered(source, anchor["line"],
                                                                                     anchor["endLine"]), ""]
    lines.append("## Unknowns and non-defects (proposed)")
    for ident, text in zip(unknown_ids(task_id, ledger), ledger["unknowns"]):
        lines.append(f"- {ident}: {one_line(text)}")
    for ident, text in zip(nondefect_ids(task_id, ledger), ledger["nonDefects"]):
        lines.append(f"- {ident}: {one_line(text)}")
    lines.append("")
    return "\n".join(lines), len(ledger["facts"]), anchors, mismatches


def _numbered(source: list[str], start: int, end: int, margin: int = 5) -> list[str]:
    count = er.human_line_count(source)
    first, last = max(1, start - margin), min(count, end + margin)
    body = source[first - 1:last]
    longest = max((len(run) for text in body for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    width = len(str(last))
    out = [f"{fence}text"]
    for number in range(first, last + 1):
        marker = ">" if start <= number <= end else " "
        out.append(f"{marker} {number:>{width}} | {source[number - 1]}")
    out.append(fence)
    return out


# --------------------------------------------------------------------------------------------
# Freeze


@dataclass
class Campaign:
    """A derived campaign: campaign-relative files, the new tasks.json and what went wrong."""

    name: str
    files: dict[str, bytes] = field(default_factory=dict)
    tasks_after: bytes | None = None
    problems: list[tuple[str, str]] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    policy: PolicyCheck | None = None
    leak_findings: int = 0
    notes: list[str] = field(default_factory=list)
    revision: str | None = None

    def fail(self, what: str, action: str) -> None:
        self.problems.append((what, action))


def _heldout_projection(manifest: dict) -> dict:
    return {"hosts": manifest.get("hosts"), "repetitions": manifest.get("repetitions"),
            "pilotTargets": manifest.get("pilotTargets"),
            "tasks": [{key: task.get(key) for key in ("id", "repository", "url", "commit", "entrypoints", "prompt")}
                      for task in manifest.get("tasks") or [] if task.get("split") == "heldout"]}


def _canonical_manifest(value: dict) -> bytes:
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def _tooling() -> dict[str, str]:
    return {rel: er.sha256_file(ROOT / rel) for rel in TOOLING_FILES}


def _verify_corpus(world: World, task: dict) -> str | None:
    """None when fetch_workflow_repos.verify_repo accepts the task's checkout, else why not."""
    fetcher = _sibling("fetch_workflow_repos")
    verify = getattr(fetcher, "verify_repo", None) if fetcher is not None else None
    if not callable(verify):
        return "corpus verification is not available in this build (tools/fetch_workflow_repos.py has no verify_repo)"
    repo = world.repo_entry(task)
    if repo is None:
        return f"{task.get('repository')} is not listed in {REPOSITORIES_REL}"
    try:
        report = verify(repo, world.corpus)
    except Exception as exc:  # noqa: BLE001 - any failure of the verifier refuses the freeze
        return f"verify_repo failed: {exc}"
    if not isinstance(report, dict) or report.get("ok") is not True:
        details = []
        if isinstance(report, dict):
            for key in ("head", "clean", "sparseMatches", "missing", "extraMaterialized", "blobMismatches"):
                if key in report and report[key] not in (True, [], None) and key != "head":
                    details.append(f"{key}: {report[key]}")
        return "verify_repo reported a problem" + (f" ({'; '.join(details)})" if details else "")
    return None


def derive_campaign(world: World, campaign: str, *, frozen_at: str, tooling: dict | None = None,
                    supersedes: dict | None = None, existing: dict | None = None, verify_corpus: bool = True) -> Campaign:
    """Derive every frozen file of ``campaign`` from the owner files, ledgers and manifests.

    ``existing`` (check-frozen) is the committed freeze.json: its tasksManifest.sha256 and
    developmentAdjudication are reused, and when the corpus is absent the committed
    sourceFiles hashes stand in for the pinned bytes.
    """
    result = Campaign(campaign)
    manifest = world.manifest
    existing_refs: dict[str, dict] = {}
    if existing is not None:
        for task in world.heldout:
            path = world.root / PILOT_REL / campaign / "reference" / f"{task['id']}.json"
            try:
                existing_refs[task["id"]] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                existing_refs[task["id"]] = {}
    references: dict[str, dict] = {}
    decision_hashes: dict[str, str] = {}
    candidate_hashes: dict[str, str] = {}
    corpus_missing = verify_corpus and world.corpus is None
    if corpus_missing:
        result.fail("the corpus is absent; the freeze needs every pinned repository",
                    "set MLVIEW_PUBLIC_CORPUS_DIR or run python tools/fetch_workflow_repos.py")
    for task in world.heldout:
        task_id = task["id"]
        rel = f"{DECISIONS_REL}/{task_id}.md"
        path = world.root / rel
        if not path.is_file():
            result.fail(f"{rel} does not exist", f"{TEMPLATE_COMMAND} {task_id}")
            continue
        checks = check_path(world, path)
        primary = checks[0].result
        assert isinstance(primary, RefCheck)
        for check in checks:
            if check.errors or check.todos or not getattr(check.result, "ready", False):
                result.fail(f"{check.display}: {check.errors} error(s), {check.todos} to do"
                            + ("" if check.errors or check.todos else ', "Review: complete" missing'),
                            f"{CHECK_COMMAND} {task_id}")
        if not primary.ready or (primary.second is not None and not primary.second.ready):
            continue
        decision_hashes[rel] = primary.record.sha256
        reviews = [_review_entry(rel, primary)]
        if primary.second is not None:
            second_rel = f"{DECISIONS_REL}/{task_id}.second.md"
            decision_hashes[second_rel] = primary.second.record.sha256
            reviews.append(_review_entry(second_rel, primary.second))
        ledger, ledger_raw = world.ledger(task_id)
        candidate_hashes[f"{CANDIDATES_REL}/{task_id}.json"] = er.sha256_bytes(ledger_raw)
        reference = _reference(world, task, campaign, primary, reviews, ledger, ledger_raw)
        if corpus_missing:
            continue
        sources = _source_files(world, task, reference, ledger, result, existing_refs.get(task_id))
        if sources is None:
            continue
        reference["sourceFiles"] = sources
        references[task_id] = reference
    policy_rel = f"{DECISIONS_REL}/{POLICY_TARGET}.md"
    policy_path = world.root / policy_rel
    policy = None
    if not policy_path.is_file():
        result.fail(f"{policy_rel} does not exist", f"{TEMPLATE_COMMAND} {POLICY_TARGET}")
    else:
        policy_raw = policy_path.read_bytes()
        policy = check_policy(world, policy_raw, policy_rel)
        result.policy = policy
        if not policy.ready:
            result.fail(f"{policy_rel}: {policy.errors} error(s), {policy.todos} to do"
                        + ("" if policy.errors or policy.todos else ', "Review: complete" missing'),
                        f"{CHECK_COMMAND} {POLICY_TARGET}")
        else:
            decision_hashes[policy_rel] = policy.record.sha256
    if verify_corpus and not corpus_missing:
        for task in world.heldout:
            problem = _verify_corpus(world, task)
            if problem:
                result.fail(f"{task.get('repository')}: {problem}", "python tools/fetch_workflow_repos.py --verify")
    if result.problems or policy is None or not policy.ready:
        return result
    # Prompts, leak and machine-path checks.
    leak_texts = _leak_texts(world, references)
    prompts: dict[str, bytes] = {}
    for task in world.heldout:
        scenario = references[task["id"]]["scenario"]
        for folder, template in (("skill", policy.skill_template), ("baseline", policy.baseline_template)):
            rel = f"prompts/{folder}/{task['id']}.txt"
            text = render_prompt(template, task, scenario)
            for problem in _prompt_findings(rel, text, leak_texts):
                result.leak_findings += 1
                result.fail(problem, "edit the scenario in the task's decisions file or the prompt template")
            prompts[rel] = text.encode("utf-8")
    if result.problems:
        return result
    files: dict[str, bytes] = {}
    for task in world.heldout:
        files[f"reference/{task['id']}.json"] = er.canonical_json(references[task["id"]])
    reference_set = {
        "format": "mlview-reference-set/1", "campaign": campaign, "frozenAt": frozen_at,
        "tasks": [{"task": task["id"], "path": f"reference/{task['id']}.json",
                   "sha256": er.sha256_bytes(files[f"reference/{task['id']}.json"]),
                   "essential": references[task["id"]]["counts"]["essential"],
                   "runsMustState": references[task["id"]]["counts"]["runsMustState"]} for task in world.heldout],
        "totals": {key: sum(references[task["id"]]["counts"][key] for task in world.heldout)
                   for key in ("facts", "essential", "runsMustState", "nonDefects", "defects")} | {
                       "tasks": len(world.heldout)},
        "note": NOTE_TEXT,
    }
    files["reference-set.json"] = er.canonical_json(reference_set)
    revision = "sha256:" + er.sha256_bytes(files["reference-set.json"])
    result.revision = revision
    files["policy.json"] = er.canonical_json(policy_record(world, policy, policy_rel, policy_path.read_bytes(), campaign))
    files.update(prompts)
    after = copy.deepcopy(manifest)
    for task in after.get("tasks") or []:
        if task.get("split") == "heldout":
            task["referenceStatus"] = "frozen"
    after.pop("pilotFreeze", None)
    after["pilotFreeze"] = {"campaign": campaign, "freeze": f"pilot/{campaign}/freeze.json", "referenceRevision": revision}
    result.tasks_after = _canonical_manifest(after)
    adjudication = _adjudication_binding(world)
    tasks_sha = er.sha256_bytes(result.tasks_after)
    if existing is not None:
        tasks_sha = (existing.get("tasksManifest") or {}).get("sha256")
        adjudication = existing.get("developmentAdjudication")
    repositories = world.repositories
    freeze = {
        "format": "mlview-freeze/1", "campaign": campaign, "frozenAt": frozen_at, "referenceRevision": revision,
        "supersedes": supersedes,
        "files": {rel: er.sha256_bytes(data) for rel, data in sorted(files.items())},
        "decisionFiles": dict(sorted(decision_hashes.items())),
        "candidateLedgers": dict(sorted(candidate_hashes.items())),
        "tasksManifest": {"sha256": tasks_sha, "heldOut": _heldout_projection(manifest)},
        "repositories": {"sha256": er.sha256_bytes(world.repositories_bytes()),
                         "sparse": {repo.get("name"): list(repo.get("sparse") or [])
                                    for repo in repositories.get("repos") or []}},
        "developmentAdjudication": adjudication,
        "tooling": dict(tooling) if tooling is not None else _tooling(),
        "note": NOTE_TEXT,
    }
    files["freeze.json"] = er.canonical_json(freeze)
    result.files = files
    for task in world.heldout:
        reference = references[task["id"]]
        primary_reviews = [review["reviewer"] for review in reference["reviews"]]
        result.rows.append({"task": task["id"], "facts": reference["counts"]["facts"],
                            "essential": reference["counts"]["essential"],
                            "rejected": len(reference["rejectedFacts"]),
                            "added": sum(1 for fact in reference["facts"] if fact["origin"] == "added"),
                            "runsMustState": reference["counts"]["runsMustState"],
                            "reviewers": "; ".join(primary_reviews)})
    if policy.values.get("developmentAdjudication") == "required":
        complete = bool(adjudication and adjudication.get("complete"))
        result.notes.append("the run policy requires the development adjudication before Stage 1; run-prepare will "
                            "refuse Stage 1 runs until evals/workflow/decisions/development-adjudication.md is complete"
                            + ("" if complete else " (it is not complete now)") + ".")
    return result


def _review_entry(rel: str, result: RefCheck) -> dict:
    return {"role": result.role, "path": rel, "sha256": result.record.sha256, "reviewer": result.reviewer,
            "date": result.date, "transcribedBy": result.transcribed_by or None}


def _reference(world: World, task: dict, campaign: str, primary: RefCheck, reviews: list[dict], ledger: dict,
               ledger_raw: bytes) -> dict:
    facts = primary.facts
    essential = [fact["id"] for fact in facts if fact["essential"]]
    must = [item for item in primary.unknowns if item["runsMustState"]]
    return {
        "format": "mlview-frozen-reference/1", "campaign": campaign, "task": task["id"],
        "repository": task["repository"], "repositoryCommit": task["commit"],
        "candidate": {"path": f"{CANDIDATES_REL}/{task['id']}.json", "sha256": er.sha256_bytes(ledger_raw)},
        "reviews": reviews,
        "scenario": dict(primary.scenario),
        "facts": facts, "rejectedFacts": primary.rejected_facts, "essentialFactIds": essential,
        "knownUnresolved": primary.unknowns, "rejectedUnknowns": primary.rejected_unknowns,
        "nonDefects": primary.nondefects, "rejectedNonDefects": primary.rejected_nondefects,
        "defects": primary.defects, "disputes": primary.disputes,
        "counts": {"facts": len(facts), "essential": len(essential), "runsMustState": len(must),
                   "nonDefects": len(primary.nondefects), "defects": len(primary.defects)},
    }


def _source_files(world: World, task: dict, reference: dict, ledger: dict, result: Campaign,
                  existing: dict | None) -> dict | None:
    """sourceFiles of a frozen reference: every anchor file and scenario entrypoint, pinned by
    SHA-256 and blob. Verifies kept candidate quotes and new locators against the pinned bytes."""
    task_id, repo_name = task["id"], task.get("repository")
    repo = world.repo_entry(task)
    if repo is None:
        result.fail(f"{task_id}: {repo_name} is not listed in {REPOSITORIES_REL}", f"fix {REPOSITORIES_REL}")
        return None
    patterns = list(repo.get("sparse") or [])
    quotes = {anchor["id"]: anchor for fact in ledger["facts"] for anchor in fact["anchors"]}
    anchors = [anchor for fact in reference["facts"] for anchor in fact["anchors"]]
    anchors += [anchor for defect in reference["defects"] for anchor in defect["anchors"]]
    paths = sorted(set(reference["scenario"]["entrypoints"]) | {anchor["file"] for anchor in anchors})
    ok = True
    for path in paths:
        try:
            covered = er.sparse_covers(patterns, path)
        except ValueError as exc:
            result.fail(f"{task_id}: {path}: {exc}", "fix the path in the decisions file")
            ok = False
            continue
        if not covered:
            result.fail(f"{task_id}: {path} is not fetched by repositories.json ({repo_name} sparse list)",
                        "ask the maintainer to add it to the sparse list, then python tools/fetch_workflow_repos.py "
                        "--update-sparse")
            ok = False
    present = world.repo_dir(task) is not None
    if not present:
        recorded = (existing or {}).get("sourceFiles")
        if not isinstance(recorded, dict):
            result.fail(f"{task_id}: the corpus is absent and no committed sourceFiles exist",
                        "set MLVIEW_PUBLIC_CORPUS_DIR or run python tools/fetch_workflow_repos.py")
            return None
        missing = [path for path in paths if path not in recorded]
        if missing:
            result.fail(f"{task_id}: sourceFiles would add {', '.join(missing)} (corpus absent; cannot hash them)",
                        "run check-frozen with the corpus present")
            return None
        return {path: recorded[path] for path in paths} if ok else None
    sources: dict[str, dict] = {}
    try:
        tree = world.tree(task)
    except ValueError as exc:
        result.fail(f"{task_id}: cannot read the pinned tree: {exc}", "python tools/fetch_workflow_repos.py --verify")
        return None
    assert tree is not None
    for path in paths:
        if path not in tree:
            result.fail(f"{task_id}: {path} is not in the pinned {repo_name} tree at {task['commit'][:12]}",
                        "fix the path in the decisions file")
            ok = False
            continue
        try:
            data = world.pinned(task, path)
        except ValueError as exc:
            result.fail(f"{task_id}: {exc}", "python tools/fetch_workflow_repos.py --verify")
            ok = False
            continue
        sources[path] = {"sha256": er.sha256_bytes(data), "blob": er.git_blob_oid(data)}
    if not ok:
        return None
    for anchor in anchors:
        data = world.pinned(task, anchor["file"])
        try:
            lines = er.source_lines(data, anchor.get("cell"), world.helper)
            er.excerpt(lines, anchor["line"], anchor["endLine"])
        except ValueError as exc:
            result.fail(f"{task_id}: {anchor['id']} ({_locator(anchor)}) does not resolve: {exc}",
                        f"{CHECK_COMMAND} {task_id}")
            ok = False
            continue
        if anchor["endLine"] > er.human_line_count(lines):
            result.fail(f"{task_id}: {anchor['id']} ({_locator(anchor)}) is out of range", f"{CHECK_COMMAND} {task_id}")
            ok = False
            continue
        candidate = quotes.get(anchor["id"])
        if candidate is not None and not er.quote_matches(candidate.get("quote"), lines, anchor["line"],
                                                          anchor["endLine"], world.helper):
            result.fail(f"{task_id}: the candidate quote of {anchor['id']} ({_locator(anchor)}) differs from the "
                        "pinned bytes", "python tools/fetch_workflow_repos.py --verify")
            ok = False
    return sources if ok else None


def _adjudication_binding(world: World) -> dict | None:
    rel = f"{DECISIONS_REL}/{ADJUDICATION_TARGET}.md"
    path = world.root / rel
    if not path.is_file():
        return None
    raw = path.read_bytes()
    try:
        complete = check_adjudication(world, raw, rel).complete
    except UsageError:
        complete = False
    return {"path": rel, "sha256": er.sha256_bytes(raw), "complete": complete}


def _supersede_check(world: World, campaign: str, reason: str | None, result: Campaign) -> dict | None:
    """The supersedes record, or None; problems go to ``result``."""
    manifest = world.manifest
    problems = er.check_task_manifest(manifest)
    for problem in problems:
        result.fail(f"{TASKS_REL}: {problem}", f"fix {TASKS_REL}")
    freeze = manifest.get("pilotFreeze")
    if freeze is None:
        not_prefreeze = [task["id"] for task in world.heldout if task.get("referenceStatus") != "needs-human-review"]
        if not_prefreeze:
            result.fail(f"{TASKS_REL}: {', '.join(not_prefreeze)} not needs-human-review", f"fix {TASKS_REL}")
        if reason:
            result.fail("--supersede-reason was given but no campaign is frozen", "drop --supersede-reason")
        return None
    old = freeze.get("campaign") if isinstance(freeze, dict) else None
    if not reason:
        result.fail(f"{TASKS_REL} is not in the pre-freeze state: campaign {old} is frozen",
                    f'a new campaign may supersede {old} only with --supersede-reason "<why>", and only if {old} has '
                    "no committed candidate.json or has an owner-authored invalidation.md")
        return None
    if old == campaign:
        result.fail(f"campaign {campaign} is the one already frozen", "choose a new campaign name")
        return None
    old_dir = world.root / PILOT_REL / str(old)
    if (old_dir / "candidate.json").exists():
        invalidation = old_dir / "invalidation.md"
        problem = _invalidation_problem(invalidation, str(old))
        if problem:
            result.fail(f"{old} has a candidate.json, so it can be superseded only after an owner-authored "
                        f"invalidation.md ({problem})", f"the owner writes {world.display(invalidation)}")
            return None
    return {"campaign": old, "reason": reason}


def _invalidation_problem(path: Path, campaign: str) -> str | None:
    if not path.is_file():
        return "it does not exist"
    record, problems = er.parse_record(path.read_bytes(), str(path))
    if record is None or problems:
        return "it does not parse"
    if record.kind != "Invalidation" or record.ident != campaign:
        return f'its title must read "# Invalidation: {campaign}"'
    missing = [key for key in ("Reviewer", "Date", "Scope", "Reason") if not _value(record.header, key)]
    if missing:
        return f"{', '.join(missing)} empty"
    if _value(record.header, "Scope").casefold() not in ("stage1", "campaign"):
        return "Scope must be stage1 or campaign"
    if not _valid_date(_value(record.header, "Date")):
        return "Date is not YYYY-MM-DD"
    return None


def freeze(world: World, campaign: str, *, write: bool, frozen_at: str | None, supersede_reason: str | None,
           out) -> int:
    if not isinstance(campaign, str) or not er.NAME_RE.fullmatch(campaign):
        raise UsageError(f"--campaign must be a lowercase name such as pilot-01, not {campaign!r}")
    frozen_at = frozen_at or er.rfc3339_utc_now()
    if not er.is_rfc3339(frozen_at) or not frozen_at.endswith("Z"):
        raise UsageError(f"--frozen-at must be an RFC 3339 UTC time such as 2026-10-05T10:00:00Z, not {frozen_at!r}")
    tasks_before = world.manifest_bytes()
    gate = Campaign(campaign)
    if _canonical_manifest(world.manifest) != tasks_before:
        gate.fail(f"{TASKS_REL} is not canonical JSON (json.dumps(indent=2) plus a newline)",
                  f"restore {TASKS_REL} to its canonical formatting")
    supersedes = _supersede_check(world, campaign, supersede_reason, gate)
    target = world.root / PILOT_REL / campaign
    if target.exists():
        gate.fail(f"{world.display(target)} already exists", "choose a new campaign name; frozen campaigns are never "
                                                             "overwritten")
    derived = derive_campaign(world, campaign, frozen_at=frozen_at, supersedes=supersedes)
    problems = gate.problems + derived.problems
    if problems:
        print(f"Cannot freeze {campaign} (nothing written):", file=out)
        for what, action in problems:
            print(f"  - {what.rstrip('.')}. Next: {action}", file=out)
        return 1
    heldout = len(world.heldout)
    verb = "Would write" if not write else "Wrote"
    header = (f"Ready to freeze {campaign} (dry run; nothing written)" if not write
              else f"Froze {campaign} at {frozen_at} (referenceRevision {derived.revision})")
    if write:
        _write_campaign(world, target, derived, tasks_before)
    print(header, file=out)
    print(f"  {'task':<18}{'facts':>7}{'essential':>11}{'rejected':>10}{'added':>7}{'runs-must-state':>17}  reviewers",
          file=out)
    for row in derived.rows:
        print(f"  {row['task']:<18}{row['facts']:>7}{row['essential']:>11}{row['rejected']:>10}{row['added']:>7}"
              f"{row['runsMustState']:>17}  {row['reviewers']}", file=out)
    totals = {key: sum(row[key] for row in derived.rows) for key in ("facts", "essential", "rejected", "added",
                                                                     "runsMustState")}
    print(f"  {'total':<18}{totals['facts']:>7}{totals['essential']:>11}{totals['rejected']:>10}{totals['added']:>7}"
          f"{totals['runsMustState']:>17}", file=out)
    policy = derived.policy
    assert policy is not None
    print(f"  run policy: ready ({policy.reviewer}, {policy.date}); prompts: {2 * heldout} rendered, "
          f"{derived.leak_findings} leak findings", file=out)
    for note in derived.notes:
        print(f"  note: {note}", file=out)
    print(f"{verb} {PILOT_REL}/{campaign}/ ({heldout} references, reference-set.json, policy.json, {2 * heldout} "
          "prompts, freeze.json)", file=out)
    if supersedes is not None:
        change = (f"pilotFreeze {supersedes['campaign']} -> {campaign} (supersedes {supersedes['campaign']}: "
                  f"{supersedes['reason']})")
    else:
        change = f"{heldout} held-out referenceStatus -> frozen; add pilotFreeze"
    print(f"{'Would update' if not write else 'Updated'} {TASKS_REL}: {change}", file=out)
    if not write:
        print("Re-run with --write. Frozen files are created exclusively and never overwritten.", file=out)
    else:
        print(f"Next: commit {DECISIONS_REL}, {PILOT_REL}/{campaign} and {TASKS_REL} together. The freeze records the "
              "reviewers' decisions; it does not add an approval.", file=out)
    return 0


def _write_campaign(world: World, target: Path, derived: Campaign, tasks_before: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    os.mkdir(target)  # exclusive: FileExistsError when another freeze got there first
    created: list[Path] = []
    try:
        for rel in sorted(derived.files, key=lambda item: (item == "freeze.json", item)):
            path = target / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            er.write_exclusive(path, derived.files[rel])
            created.append(path)
        tasks_path = world.root / TASKS_REL
        if tasks_path.read_bytes() != tasks_before:
            raise RuntimeError(f"{TASKS_REL} changed during the freeze; nothing was kept")
        assert derived.tasks_after is not None
        er.write_atomic(tasks_path, derived.tasks_after)
    except BaseException:
        for path in reversed(created):
            try:
                path.unlink()
            except OSError:
                pass
        for directory in sorted({p.parent for p in created} | {target}, key=lambda p: len(p.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise
    world.reload_manifest()


# --------------------------------------------------------------------------------------------
# check-frozen


def _final_summary_recorded(directory: Path) -> bool:
    if (directory / "stage2-summary.json").is_file():
        return True
    path = directory / "stage1-summary.json"
    if not path.is_file():
        return False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    decision = value.get("decision") if isinstance(value, dict) else None
    return isinstance(decision, dict) and decision.get("value") in ("stop", "invalid")


def _integrity(world: World, directory: Path, problems: list[str]) -> dict | None:
    """Hash-integrity check of one committed campaign directory; returns its freeze.json."""
    label = world.display(directory)
    try:
        freeze_value = json.loads((directory / "freeze.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problems.append(f"{label}/freeze.json cannot be read: {exc}")
        return None
    files = freeze_value.get("files") if isinstance(freeze_value, dict) else None
    if not isinstance(files, dict):
        problems.append(f"{label}/freeze.json has no files map")
        return None
    for rel, digest in sorted(files.items()):
        try:
            data = er.confined_file(directory, rel).read_bytes()
        except ValueError as exc:
            problems.append(f"{label}/{rel}: {exc}")
            continue
        if er.sha256_bytes(data) != digest:
            problems.append(f"{label}/{rel} differs from its hash in freeze.json (frozen files are immutable)")
    try:
        reference_set = (directory / "reference-set.json").read_bytes()
        if freeze_value.get("referenceRevision") != "sha256:" + er.sha256_bytes(reference_set):
            problems.append(f"{label}: referenceRevision does not match reference-set.json")
    except OSError as exc:
        problems.append(f"{label}/reference-set.json cannot be read: {exc}")
    for sub in ("reference", "prompts/skill", "prompts/baseline"):
        folder = directory / sub
        if folder.is_dir():
            for path in sorted(folder.iterdir()):
                rel = path.relative_to(directory).as_posix()
                if rel not in files:
                    problems.append(f"{label}/{rel} is not listed in freeze.json")
    return freeze_value


def check_frozen(world: World, out) -> int:
    pilot_dir = world.root / PILOT_REL
    campaigns = sorted(path.parent for path in pilot_dir.glob("*/freeze.json")) if pilot_dir.is_dir() else []
    manifest = world.manifest
    freeze_pointer = manifest.get("pilotFreeze")
    problems: list[str] = []
    notes: list[str] = []
    for problem in er.check_task_manifest(manifest):
        problems.append(f"{TASKS_REL}: {problem}")
    current = freeze_pointer.get("campaign") if isinstance(freeze_pointer, dict) else None
    if freeze_pointer is None:
        for directory in campaigns:
            problems.append(f"{world.display(directory)}/freeze.json exists but {TASKS_REL} has no pilotFreeze")
        if not problems:
            print(f"check-frozen: no frozen campaign ({TASKS_REL} has no pilotFreeze); nothing to check.", file=out)
            return 0
    for directory in campaigns:
        if directory.name == current:
            continue
        before = len(problems)
        _integrity(world, directory, problems)
        if len(problems) == before:
            notes.append(f"check-frozen: {directory.name} (superseded): hashes intact.")
    if current is not None:
        directory = pilot_dir / current
        before = len(problems)
        existing = None
        if not (directory / "freeze.json").is_file():
            problems.append(f"{TASKS_REL} names {freeze_pointer.get('freeze')}, which does not exist")
        else:
            existing = _integrity(world, directory, problems)
        if existing is not None:
            if existing.get("referenceRevision") != freeze_pointer.get("referenceRevision"):
                problems.append(f"{TASKS_REL} pilotFreeze.referenceRevision differs from {current}/freeze.json")
            held_out = _heldout_projection(manifest)
            if (existing.get("tasksManifest") or {}).get("heldOut") != held_out:
                problems.append(f"{TASKS_REL} held-out fields changed after the freeze of {current} "
                                "(hosts, repetitions, pilotTargets or a held-out task's id, repository, url, commit, "
                                "entrypoints or prompt); a changed reference needs a new campaign")
            if _final_summary_recorded(directory):
                if len(problems) == before:
                    notes.append(f"check-frozen: {current} (final summary recorded): hashes intact.")
            elif len(problems) == before:
                derived = derive_campaign(world, current, frozen_at=existing.get("frozenAt"),
                                          tooling=existing.get("tooling"), supersedes=existing.get("supersedes"),
                                          existing=existing, verify_corpus=False)
                if derived.problems:
                    for what, action in derived.problems:
                        problems.append(f"{current} cannot be re-derived: {what}. Next: {action}")
                else:
                    on_disk = {path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()}
                    for rel, data in sorted(derived.files.items()):
                        try:
                            actual = er.confined_file(directory, rel).read_bytes()
                        except ValueError as exc:
                            problems.append(f"{world.display(directory)}/{rel}: {exc}")
                            continue
                        if actual != data:
                            problems.append(f"{world.display(directory)}/{rel} differs from the re-derivation (an "
                                            "edited frozen file, decision file, ledger or manifest)")
                    for rel in sorted(on_disk - set(derived.files)):
                        if rel.startswith(("reference/", "prompts/")) or rel in ("reference-set.json", "policy.json"):
                            problems.append(f"{world.display(directory)}/{rel} is not produced by the freeze")
                    if len(problems) == before:
                        absent = [task.get("repository") for task in world.heldout if world.repo_dir(task) is None]
                        notes.append(f"check-frozen: {current} re-derived byte for byte ({len(world.heldout)} "
                                     f"references, reference-set.json, policy.json, {2 * len(world.heldout)} prompts, "
                                     "freeze.json); held-out tasks.json fields unchanged.")
                        if len(absent) == len(world.heldout):
                            notes.append("source hashes not re-read: corpus absent")
                        elif absent:
                            notes.append(f"source hashes not re-read for {', '.join(absent)}: corpus absent")
    for line in notes:
        print(line, file=out)
    for problem in problems:
        print(f"check-frozen: {problem}", file=out)
    return 1 if problems else 0


# --------------------------------------------------------------------------------------------
# Command line


def command_template(world: World, args, out) -> int:
    targets = template_targets(world)
    if args.init_all:
        if args.target or args.second or args.show:
            raise UsageError("--init-all takes no target, --second or --show")
        files = {name: path for name, (path, _generate) in targets.items()}
        readme = world.decisions_dir / "README.md"
        existing = [world.display(path) for path in [*files.values(), readme] if path.exists()]
        if existing:
            print("template --init-all: refusing; these files already exist and templates are never overwritten: "
                  + ", ".join(existing), file=out)
            return 1
        for name, (path, generate) in targets.items():
            er.write_exclusive(path, generate().encode("utf-8"))
            print(f"created {world.display(path)}", file=out)
        er.write_exclusive(readme, README_TEXT.encode("utf-8"))
        print(f"created {world.display(readme)}", file=out)
        print("Every value is pending. Only the named reviewer replaces them; the tool never writes decisions.",
              file=out)
        return 0
    if not args.target:
        raise UsageError("template needs a TARGET (a held-out task ID, run-policy or development-adjudication) or "
                         "--init-all")
    name = args.target
    if name not in targets:
        raise UsageError(f"{name} is not a held-out task ID, {POLICY_TARGET} or {ADJUDICATION_TARGET}")
    if args.second:
        if world.heldout_task(name) is None:
            raise UsageError("--second applies to a held-out task")
        path = world.decisions_dir / f"{name}.second.md"
        text = task_template(world, name, second=True)
    else:
        path, generate = targets[name]
        text = generate()
    if args.show:
        out.write(text)
        return 0
    try:
        er.write_exclusive(path, text.encode("utf-8"))
    except FileExistsError:
        print(f"{world.display(path)} already exists; templates are created exclusively and never overwritten. "
              f"Use {TEMPLATE_COMMAND} --show {name}{' --second' if args.second else ''} to print a pristine copy.",
              file=out)
        return 1
    print(f"created {world.display(path)} (every value pending; check it with {CHECK_COMMAND} {name})", file=out)
    return 0


def command_context(world: World, args, out) -> int:
    text, facts, anchors, mismatches = context_sheet(world, args.task)
    output = Path(args.output) if args.output else world.root / CONTEXT_REL / f"{args.task}.md"
    er.write_atomic(output, text.encode("utf-8"))
    state = "all quotes verified" if not mismatches else f"{len(mismatches)} anchor(s) NOT verified"
    print(f"wrote {world.display(output)} ({facts} facts, {anchors} anchors, {state}); local and gitignored, "
          "do not commit it", file=out)
    for mismatch in mismatches:
        print(f"  mismatch: {mismatch}", file=out)
    return 1 if mismatches else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="workflow_eval.py", description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    template = sub.add_parser("template", help="write a pending template (exclusive create)")
    template.add_argument("target", nargs="?", help="a held-out task ID, run-policy or development-adjudication")
    template.add_argument("--second", action="store_true", help="the second-review file of a task")
    template.add_argument("--show", action="store_true", help="print the pristine file instead of writing it")
    template.add_argument("--init-all", action="store_true",
                          help="create every committed template and the README (once; refuses existing files)")
    check = sub.add_parser("check", help="check owner files; never writes")
    check.add_argument("targets", nargs="*", help="task IDs, run-policy, development-adjudication or file paths")
    check.add_argument("--show-prompts", action="store_true", help="also print the 16 prompt renderings")
    context = sub.add_parser("context", help="write the local source-context sheet of one task")
    context.add_argument("task")
    context.add_argument("--output", help="the sheet's path (default .mlview/review-context/<task>.md)")
    freeze_parser = sub.add_parser("freeze", help="freeze a campaign (dry run unless --write)")
    freeze_parser.add_argument("--campaign", required=True)
    freeze_parser.add_argument("--write", action="store_true")
    freeze_parser.add_argument("--frozen-at", help="the RFC 3339 UTC freeze time (default: now)")
    freeze_parser.add_argument("--supersede-reason", help="why a new campaign supersedes the frozen one")
    sub.add_parser("check-frozen", help="re-derive the committed frozen campaign and require byte equality")
    return parser


def main(argv: Sequence[str] | None = None, *, root: Path | None = None, corpus: object = _DEFAULT,
         out=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    out = sys.stdout if out is None else out
    parser = build_parser()
    try:
        args = parser.parse_args(arguments)
    except SystemExit as exc:
        return int(exc.code or 0) if exc.code in (0, None) else 2
    world = World(root or ROOT, corpus)
    try:
        if args.command == "template":
            return command_template(world, args, out)
        if args.command == "check":
            return command_check(world, args.targets, show=args.show_prompts, out=out)
        if args.command == "context":
            return command_context(world, args, out)
        if args.command == "freeze":
            return freeze(world, args.campaign, write=args.write, frozen_at=args.frozen_at,
                          supersede_reason=args.supersede_reason, out=out)
        if args.command == "check-frozen":
            return check_frozen(world, out)
    except UsageError as exc:
        print(f"workflow_eval.py {args.command}: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"workflow_eval.py {args.command}: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
